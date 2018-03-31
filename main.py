#!/usr/bin/env python

# import ConfigParser
import argparse
import sys
import tarfile
import os
import exceptions
import logging
import shutil
import glob
import time
import yaml
import hashlib
import base64
import random
import struct
import atexit
from Crypto.PublicKey import RSA
from Crypto.Cipher import AES

# notes for feature improvement TODOs
# * integrate with https://github.com/wrmsr/pmem/tree/master/OSXPMem

class Triage():
    def __init__(self, target, encrypt, user_mode, output_location):

        logging.basicConfig(level=logging.ERROR)
        self.logger = logging.getLogger(__name__)

        # default collection items
        self.triage_items = dict()
        self.triage_items["user_mru"] = True
        self.triage_items["unified_audit_log"] = True
        self.triage_items["log_files"] = True
        self.triage_items["persistence"] = True
        self.triage_items["mdls_recurse"] = True
        self.triage_items["volatile"] = False
        self.triage_items["browser_artifacts"] = True
        self.triage_items["im_artifacts"] = True
        self.triage_items["ios_artifacts"] = True
        self.triage_items["mail_artifacts"] = True
        self.triage_items["external_media"] = True
        self.triage_items["user_artifacts"] = True
        self.triage_items["system_artifacts"] = True

        self.target = target
        self.user_mode = user_mode
        self.encrypt = encrypt

        self.live_triage = True
        self.rsa_public_key = '-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAv65A9iiP58jsheiR4ESJ\n3yYr3L5WKpDaDCpjbsq6Ac3cg7Hnpb/nrcw6V/OEPWfrovZ7A+CmTBlQuKr5rrJw\n8QMAZwE3bCD1yK1etXeAwJAnIAxYrxP9hHzd0kcv6mvRkwXcORtoZcz+rolkUkOP\nlfuOEM2zh7l4BOHTVSodxUtaevxnfOK14T9yp3qNLQGknUopJ5v0jG7rwft73zyB\nLV7rF2MVAB/u9XU8kwRGn/QPeyZ+dSzXEunow8BeZ6lDJ0Ndo2jycyN4fItitvaP\nPoM7Gfw/zU/Q53JbplqHB/+hr9TUZ3AK3px8HVZckuzQtGPdQ49DTHzIae52xm7p\nrQIDAQAB\n-----END PUBLIC KEY-----'
        self.collection_time = int(time.time())
        self.collection_dir = output_location + '/{}.collection'.format(self.collection_time)
        self.logger.info("Making collection staging directory.")
        os.makedirs(self.collection_dir)
        self.artifact_yaml_file = "20180320-macOS-artifacts.yaml"
        self.load_artifact_yaml_file()

        self.logger.info('Performing triage with the following options:')
        self.logger.info('Triage items: {}'.format(self.triage_items))
        self.logger.info('Encrypted output: {}'.format(self.rsa_public_key != ''))

    ##########################################
    # HELPER FUNCTIONS
    ##########################################

    # PRE-COLLECTION
    def load_artifact_yaml_file(self):
        try:
            yaml_artifacts = yaml.load_all(open(self.artifact_yaml_file, 'r'))
        except yaml.YAMLError as e:
            self.logger.critical("macOS artifact yaml file was not parsed properly: {} Exiting.".format(e))
            sys.exit(1)
        except IOError as e:
            self.logger.critical("macOS artifact yaml file not found: {} Exiting.".format(e))
            sys.exit(1)

        self.artifact_list = list()
        for a in yaml_artifacts:
            self.artifact_list.append(a)

    # PRE-COLLECTION
    def determine_live_or_dead(self):
        # if target is the root file system, this is a live triage
        if self.target == "/":
            self.live_triage = True
        else:
            self.live_triage = False

    # COLLECTION
    def collect_category(self, category):
        self.logger.debug("Attempting to collect category {}".format(category))
        for artifact in self.artifact_list:
            if category in artifact['labels']:
                for path in artifact['sources'][0]['attributes']['paths']:
                    try:
                        if type(path) == list: path = path[0]
                        self.collect_artifact(path.replace('%%users.homedir%%','/Users/*'))
                    except IOError as e:
                        self.logger.error("Could not collect artifact {}: {}".format(path[0], e))
                    except OSError as e:
                        self.logger.error("Could not collect artifact {}: {}".format(path[0], e))

    # COLLECTION
    def perform_triage(self):
        self.determine_live_or_dead()

        # root permission check
        if os.getuid() != 0:
            self.logger.warn('[!] Triage script is not running as root, artifacts able to be collected will be limited.')
            self.is_root = False
            if not self.user_mode:
                self.logger.critical('[!] Triage attempted to be performed without the user_mode override flag being set. Exiting.')
                sys.exit(1)
        else:
            self.is_root = True

        if self.encrypt and self.rsa_public_key == "":
            self.logger.critical('[!] Triage encryption option enabled, but rsa_public_key is empty. Exiting..')
            sys.exit(1)

        if self.triage_items["user_mru"]: self.collect_category("MRU")
        if self.triage_items["unified_audit_log"]: self.collect_ual()
        if self.triage_items["log_files"]: self.collect_category("Logs")
        if self.triage_items["persistence"]: self.collect_category("Autoruns")
        if self.triage_items["mdls_recurse"]: self.mdls_search()
        if self.triage_items["volatile"]: self.collect_volatile()
        if self.triage_items["browser_artifacts"]: self.collect_category("Browser")
        if self.triage_items["im_artifacts"]: self.collect_category("IM")
        if self.triage_items["ios_artifacts"]: self.collect_category("IOS")
        if self.triage_items["mail_artifacts"]: self.collect_category("Mail")
        if self.triage_items["external_media"]: self.collect_category("External Media")
        if self.triage_items["user_artifacts"]: self.collect_category("User")
        if self.triage_items["system_artifacts"]: self.collect_category("System")

        self.compress_collection()

        if self.rsa_public_key != '' and self.encrypt:
            self.logger.info("Encrypting output file.")
            self.encrypt_output()

    # COLLECTION
    def collect_artifact(self, path, collection_subdirectory=''):

        if not self.live_triage:
            path = self.target + path
        self.logger.debug("Attempting to collect artifact {}".format(path))
        for item in glob.glob(path):
            # create collection staging directory path for item.
            # collection_subdirectory is used for special cases like unified audit logs and volitile data.
            collection_path = self.collection_dir + collection_subdirectory + os.path.abspath(item)
            if os.path.exists(collection_path):
                self.logger.debug("Directory exists for {}, skipping directory creation.".format(item))
            else:
                self.logger.info("Making a new collection directory for {}.".format(item))
                os.makedirs(collection_path)

            # directory collection
            if os.path.isdir(item):
                collection_path = self.collection_dir + collection_subdirectory + os.path.abspath(item)
                self.logger.info("Collecting directory {}".format(item))
                self._copytree(item, collection_path)
            # file collection
            else:
                self.logger.info("Collecting file {}".format(item))
                shutil.copy2(item, collection_path)

    # COLLECTION
    def _copytree(self, src, dst, symlinks=False, ignore=None):
        for item in os.listdir(src):
            s = os.path.join(src, item)
            d = os.path.join(dst, item)
            try:
                if os.path.isdir(s):
                    shutil.copytree(s, d, symlinks, ignore)
                else:
                    shutil.copy2(s, d)
            except shutil.Error as e:
                self.logger.error("Copytree error: {}".format(e))

    ##########################################
    # NON STANDARD COLLECTION FUNCTIONS
    ##########################################
    def collect_volatile(self):
        os.popen('netstat -an').read()
        os.popen('ps aux').read()
        os.popen('w').read()
        # fix this cmd
        os.popen('cat /Users/*/.ssh/known_hosts').read()

    def collect_ual(self):
        if self.is_root:
            if self.live_triage:
                    os.system("log collect --output {}/ual_collection.logarchive".format(self.collection_dir))
            else:
                try:
                    # collect UAL directories into COLLECTION_ROOT/ual_collection
                    # rename COLLECTION_ROOT/ual_collection to COLLECTION_ROOT/ual_collection.logarchive
                    self.collect_artifact('/var/db/diagnostics/*', "/ual_collection")
                    self.collect_artifact('/var/db/uuidtext/*', "/ual_collection")
                    os.rename(self.collection_dir + '/ual_collection', self.collection_dir + '/ual_collection.logarchive')
                except IOError as e:
                    self.logger.error("Could not collect artifact: {}".format(e))
                except OSError as e:
                    self.logger.error("Could not collect artifact: {}".format(e))
        else:
            self.logger.warn("UAL collection selected, but triage is not running as root. Skipping UAL collection.")

    def mdls_search(self):
        mdls_user_directories = ['Applications','Desktop','Documents','Downloads','Library']

        for d in mdls_user_directories:
            for directory in glob.glob('/Users/*/{}'.format(d)):
                for tgtfile in os.listdir(directory):
                    try:
                        self.mdls_collect(tgtfile, directory)
                    except IOError as e:
                        self.logger.error("Could not run mdls on artifact: {}".format(e))
                    except OSError as e:
                        self.logger.error("Could not run mdls on artifact: {}".format(e))

        mdls_system_directories = ["/Applications"]
        for directory in mdls_system_directories:
            for tgtfile in os.listdir(directory):
                try:
                    self.mdls_collect(tgtfile, directory)
                except IOError as e:
                    self.logger.error("Could not run mdls on artifact: {}".format(e))
                except OSError as e:
                    self.logger.error("Could not run mdls on artifact: {}".format(e))

    def mdls_collect(self, tgtfile, directory):
        mdls_collection_dir = os.path.join(self.collection_dir, 'mdls_collection')
        # os.mkdir(mdls_collection_dir)
        mdls_tgt_path = os.path.join(directory, tgtfile)
        mdls_collection_path = mdls_collection_dir + directory
        # if os.path.isfile(mdls_tgt_path):
        if os.path.exists(mdls_collection_path):
            self.logger.debug("Directory exists for {}, skipping directory creation.".format(mdls_collection_path))
        else:
            self.logger.info("Making a new collection directory for {}.".format(mdls_collection_path))
            os.makedirs(mdls_collection_path)
        os.system('mdls -plist "{}" "{}"'.format(mdls_collection_path + '/' + tgtfile + '.mdls.plist',  mdls_tgt_path))


    def md5_program_folders(self):
        pass

    def collect_pmem(self):
        pass

    # POST-COLLECTION
    def compress_collection(self):
        self.logger.info("Compressing collection output into tar gzip file.")
        tar = tarfile.open('{}.collection.tar.gz'.format(self.collection_time), 'w:gz')
        tar.add('{}.collection'.format(self.collection_time), recursive=True)
        tar.close()

        self.logger.info("Deleting collection directory.")
        shutil.rmtree('{}.collection'.format(self.collection_time))

    # POST-COLLECTION
    class AESCipher(object):

        def __init__(self, key):
            self.bs = 32
            self.key = hashlib.sha256(key.encode()).digest()

        def encrypt(self, raw):
            raw = self._pad(raw)
            iv = Random.new().read(AES.block_size)
            cipher = AES.new(self.key, AES.MODE_CBC, iv)
            return base64.b64encode(iv + cipher.encrypt(raw))

        def decrypt(self, enc):
            enc = base64.b64decode(enc)
            iv = enc[:AES.block_size]
            cipher = AES.new(self.key, AES.MODE_CBC, iv)
            return self._unpad(cipher.decrypt(enc[AES.block_size:])).decode('utf-8')

        def _pad(self, s):
            return s + (self.bs - len(s) % self.bs) * chr(self.bs - len(s) % self.bs)

        @staticmethod
        def _unpad(s):
            return s[:-ord(s[len(s)-1:])]

    # POST-COLLECTION
    def encrypt_output(self, chunksize=64*1024):
        # create randomly generated collection key for AES
        password = os.urandom(16)
        key = hashlib.sha256(password).digest()

        # encrypt collection key with public key to make package key
        pubkey = RSA.importKey(self.rsa_public_key)
        collection_key = pubkey.encrypt(key.encode('hex'), 16)[0]

        in_filename = '{}.collection.tar.gz'.format(self.collection_time)
        out_filename = in_filename + '.enc'

        iv = ''.join(chr(random.randint(0, 0xFF)) for i in range(16))
        encryptor = AES.new(key, AES.MODE_CBC, iv)
        filesize = os.path.getsize(in_filename)

        # encrypt collection package and
        # append encrypted collection key to collection package
        with open(in_filename, 'rb') as infile:
            with open(out_filename, 'wb') as outfile:
                outfile.write(struct.pack('<Q', filesize))
                outfile.write(iv)
                while True:
                    chunk = infile.read(chunksize)
                    if len(chunk) == 0:
                        break
                    elif len(chunk) % 16 != 0:
                        chunk += ' ' * (16 - len(chunk) % 16)
                    outfile.write(encryptor.encrypt(chunk))
                # write header and collection_key to package file
                outfile.write('PKGKEY')
                outfile.write(collection_key)
        os.remove(in_filename)

def main():

    argument_parser = argparse.ArgumentParser(
        description=u'Triage script to collect artifacts from a live macOS system or mounted macOS image.')

    argument_parser.add_argument(
        u'--plaintext', dest=u'encrypt', action=u'store_false', default=True,
        help=u'Flag to turn of collection package encryption. Encryption requires rsa_public_key in Triage class init method.')

    argument_parser.add_argument(
        u'-u', u'--user-mode', dest=u'user_mode', action=u'store_true', default=False,
        help=u'Flag to override restriction of triage collection in user mode.')

    argument_parser.add_argument(
        u'-t', u'--target', dest=u'target', action=u'store', type=str,
        default="/", help=u'Target volume to run triage. Use \'/\' for live system or \'/Volume/<name>\' for a mounted volume.\
        Default option is love system.')

    argument_parser.add_argument(
        u'-o', u'--output', dest=u'output_location', action=u'store', type=str, default='.',
        help=u'Specify an output location other than the current working directory.')

    options = argument_parser.parse_args()

    t = Triage(options.target, options.encrypt, options.user_mode, options.output_location)

    @atexit.register
    def exit_handler():
        if os.path.exists(t.collection_dir):
            t.logger.info("Cleaing up collection directory {}.".format(t.collection_dir))
            shutil.rmtree(t.collection_dir)

    t.perform_triage()

if __name__ == "__main__":
    main()