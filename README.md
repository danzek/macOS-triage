# macOS triage

macOS triage is a python script to collect various macOS logs, artifacts, and other data.

## Getting Started

These instructions will get you a copy of the project up and running on your local machine for development and testing purposes. See deployment for notes on how to deploy the project on a live system.

### Prerequisites

There are a few basic dependencies for macOS triage. Ideally you would not want to install any additional programs on a target system. Eventually I will have a method to build a single executable which will be all that is needed for collection.

    pip install -r requirements.txt

### Triage

First, edit the list of triage_items in the Triage class to specify which categories are to be collected.

Next, edit the rsa_public_key in the Triage class if you plan on encrypting the output (it currently has my public key and I won't give you the private key.) See the Encrpytion Setup section for additional information.

To run the triage script, run the following:

    sudo python main.py

To run the triage script without encrypting the output, run the following:

    sudo python main.py --plaintext

The output will be a .tar.gz or .tar.gz.enc file depending on whether or not encryption was used.

## Encryption Setup

To make your own public/private key pair follow the example in a python console below:


    >>> from Crypto.PublicKey import RSA
    >>> random_generator = Random.new().read
    >>> key = RSA.generate(2048, random_generator)
    >>> print key.exportKey()
    -----BEGIN RSA PRIVATE KEY-----
    ...
    -----END RSA PRIVATE KEY-----
    # save this entire output to a file in a safe place for decryption later
    >>> print key.publickey().exportKey()
    -----BEGIN PUBLIC KEY-----
    ...
    -----END PUBLIC KEY-----
    # save this entire output to a file named 'id_rsa.pub' in the root of the script directory


## .enc Package Decryption

To decrypt an encrypted package, perform the following steps:

    python decryption/collection_package_decryptor.py -k <private key> -f <encrypted collection package>

## TODO

* ability to package triage script into a single binary with all dependencies and config information
* integrate with https://github.com/wrmsr/pmem/tree/master/OSXPMem

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Acknowledgments

* This project is indebted to the work of [@pstirparo](https://github.com/pstirparo) in the 
[mac4n6](https://github.com/pstirparo/mac4n6) project for the OSX artifact yaml file and for making it available under
the available under the 
[Creative Commons Attribution-ShareAlike 2.5 Generic (CC BY-SA 2.5) license](http://creativecommons.org/licenses/by-sa/2.5/).
