Installation
============

This guide will help you install and configure pys3local for use with backup tools like rclone and duplicati.

Prerequisites
-------------

- Python 3.9 or later
- pip (Python package installer)

Installation Methods
--------------------

Method 1: Install from PyPI (when published)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Basic installation
   pip install pys3local

   # With Drime Cloud support
   pip install pys3local[drime]

   # With development dependencies
   pip install pys3local[dev]

Method 2: Install from Source
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Clone the repository
   git clone https://github.com/holgern/pys3local.git
   cd pys3local

   # Install in development mode
   pip install -e .

   # Or with all extras
   pip install -e ".[drime,dev]"

Quick Start Guide
-----------------

1. Basic Usage (No Authentication)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Perfect for local testing:

.. code-block:: bash

   # Start server on default port (10001)
   pys3local serve --path /tmp/s3store --no-auth

   # In another terminal, test with boto3
   python3 << 'EOF'
   import boto3

   s3 = boto3.client(
       's3',
       endpoint_url='http://localhost:10001',
       aws_access_key_id='test',
       aws_secret_access_key='test'
   )

   # Create bucket
   s3.create_bucket(Bucket='test')

   # Upload file
   s3.put_object(Bucket='test', Key='hello.txt', Body=b'Hello, World!')

   # List objects
   print(s3.list_objects_v2(Bucket='test'))
   EOF

2. With Authentication
~~~~~~~~~~~~~~~~~~~~~~

For production-like setup:

.. code-block:: bash

   # Start server with authentication
   pys3local serve \
       --path /srv/s3data \
       --access-key-id mykey \
       --secret-access-key mysecret \
       --listen 0.0.0.0:10001

3. Configure rclone
~~~~~~~~~~~~~~~~~~~

Create or edit ``~/.config/rclone/rclone.conf``:

.. code-block:: ini

   [pys3local]
   type = s3
   provider = Other
   access_key_id = mykey
   secret_access_key = mysecret
   endpoint = http://localhost:10001
   region = us-east-1

Test it:

.. code-block:: bash

   # List buckets
   rclone lsd pys3local:

   # Create bucket
   rclone mkdir pys3local:backup

   # Copy files
   rclone copy /path/to/data pys3local:backup/

   # Sync (mirror) directory
   rclone sync /path/to/data pys3local:backup/

4. Configure duplicati
~~~~~~~~~~~~~~~~~~~~~~

1. Start pys3local:

.. code-block:: bash

   pys3local serve --path /srv/duplicati --access-key-id dupkey --secret-access-key dupsecret

2. In Duplicati web interface:

   - Storage Type: **S3 Compatible**
   - Server: **Custom server URL**
   - Server URL: ``http://localhost:10001``
   - Bucket name: Choose a name (e.g., ``duplicati-backups``)
   - AWS Access ID: ``dupkey``
   - AWS Secret Key: ``dupsecret``
   - Storage class: Leave blank or ``STANDARD``
   - Click "Test connection"

Configuration Management
------------------------

pys3local includes built-in configuration management for storing backend settings.

Interactive Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Enter interactive config mode
   pys3local config

   # Follow prompts to:
   # 1. List backends
   # 2. Add backend
   # 3. Show backend
   # 4. Remove backend

Manual Configuration
~~~~~~~~~~~~~~~~~~~~

Edit ``~/.config/pys3local/backends.toml``:

.. code-block:: toml

   [local-storage]
   type = "local"
   path = "/srv/s3data"

   [drime-cloud]
   type = "drime"
   api_key = "your-api-key-here"
   workspace_id = 0

Use saved configuration:

.. code-block:: bash

   pys3local serve --backend-config local-storage
   pys3local serve --backend-config drime-cloud

Obscuring Passwords
~~~~~~~~~~~~~~~~~~~

To obscure sensitive values:

.. code-block:: bash

   # Obscure a password/key
   pys3local obscure mysecretkey

   # Output:
   # Obscured password: <obscured-string>

   # Add to config file
   [mydrime]
   type = "drime"
   api_key = "<obscured-string>"
   workspace_id = 0

Running as a Service
--------------------

systemd (Linux)
~~~~~~~~~~~~~~~

Create ``/etc/systemd/system/pys3local.service``:

.. code-block:: ini

   [Unit]
   Description=pys3local S3-compatible server
   After=network.target

   [Service]
   Type=simple
   User=pys3local
   Group=pys3local
   WorkingDirectory=/srv/pys3local
   ExecStart=/usr/local/bin/pys3local serve --path /srv/s3data --access-key-id KEY --secret-access-key SECRET
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target

Enable and start:

.. code-block:: bash

   sudo systemctl daemon-reload
   sudo systemctl enable pys3local
   sudo systemctl start pys3local
   sudo systemctl status pys3local

Docker
~~~~~~

Create ``Dockerfile``:

.. code-block:: dockerfile

   FROM python:3.11-slim

   WORKDIR /app

   COPY . .

   RUN pip install --no-cache-dir .

   VOLUME /data

   EXPOSE 10001

   CMD ["pys3local", "serve", "--path", "/data", "--listen", "0.0.0.0:10001"]

Build and run:

.. code-block:: bash

   docker build -t pys3local .

   docker run -d \
       -p 10001:10001 \
       -v /srv/s3data:/data \
       -e ACCESS_KEY=mykey \
       -e SECRET_KEY=mysecret \
       --name pys3local \
       pys3local

Troubleshooting
---------------

Connection Refused
~~~~~~~~~~~~~~~~~~

Make sure the server is listening on the correct interface:

.. code-block:: bash

   # Listen on all interfaces
   pys3local serve --listen 0.0.0.0:10001

   # Check if server is running
   curl http://localhost:10001/

Authentication Errors
~~~~~~~~~~~~~~~~~~~~~

Verify credentials match:

.. code-block:: bash

   # Server side
   pys3local serve --access-key-id KEY --secret-access-key SECRET --debug

   # Client side (rclone)
   rclone config show pys3local

Permission Errors
~~~~~~~~~~~~~~~~~

Ensure the data directory is writable:

.. code-block:: bash

   # Create directory with correct permissions
   sudo mkdir -p /srv/s3data
   sudo chown $USER:$USER /srv/s3data
   chmod 700 /srv/s3data

Debug Mode
~~~~~~~~~~

Enable debug logging:

.. code-block:: bash

   pys3local serve --debug --path /tmp/s3 --no-auth

Next Steps
----------

- Read the :doc:`index` for more details
- Check the ``tests/`` directory for usage examples
- Report issues at https://github.com/holgern/pys3local/issues
