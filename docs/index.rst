.. pys3local documentation master file

pys3local Documentation
=======================

Welcome to pys3local's documentation!

**pys3local** is a local S3-compatible server designed for backup software with pluggable storage backends. It provides a full AWS S3 API implementation using FastAPI, making it perfect for local development, testing, and backup scenarios.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   installation
   quickstart
   cache_management
   project_summary

Features
--------

* ✅ **S3-Compatible API** - Full AWS S3 API implementation using FastAPI
* ✅ **Pluggable Backends** - Support for local filesystem and Drime Cloud storage
* ✅ **AWS Authentication** - Signature V2 and V4 support with presigned URLs
* ✅ **Backup Tool Integration** - Tested with rclone and duplicati
* ✅ **Configuration Management** - Built-in config management with vaultconfig
* ✅ **Rich CLI** - User-friendly command-line interface
* ✅ **Modern Stack** - FastAPI, uvicorn, Python 3.9+

Quick Start
-----------

Install pys3local:

.. code-block:: bash

   pip install pys3local

Start the server:

.. code-block:: bash

   pys3local serve --no-auth --debug

Test with boto3:

.. code-block:: python

   import boto3

   s3 = boto3.client(
       's3',
       endpoint_url='http://localhost:10001',
       aws_access_key_id='test',
       aws_secret_access_key='test'
   )

   s3.create_bucket(Bucket='mybucket')
   s3.put_object(Bucket='mybucket', Key='test.txt', Body=b'Hello!')

Use Cases
---------

* **Local Development** - Test S3-compatible applications without cloud services
* **Backup Solutions** - Use with rclone, duplicati, or other backup tools
* **CI/CD Testing** - Mock S3 storage in automated tests
* **Offline Storage** - S3-compatible storage without internet connectivity

Getting Help
------------

* **GitHub Issues**: https://github.com/holgern/pys3local/issues
* **Documentation**: Read the guides in this documentation
* **Examples**: Check the ``tests/`` directory in the repository

API Reference
-------------

.. toctree::
   :maxdepth: 2
   :caption: API Documentation:

   modules

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
