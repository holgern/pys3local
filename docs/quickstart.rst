Quick Start Guide
=================

Bucket Modes
------------

pys3local supports two bucket modes:

**Default Mode (Recommended)**

By default, pys3local uses a virtual "default" bucket. This simplifies backup tool
configuration and mirrors the behavior of drime-s3 gateway.

.. code-block:: bash

   # Start in default mode (only "default" bucket available)
   pys3local serve --no-auth --debug

**Advanced Mode**

Enable custom bucket creation with the ``--allow-bucket-creation`` flag:

.. code-block:: bash

   # Start in advanced mode (allows custom buckets)
   pys3local serve --no-auth --debug --allow-bucket-creation

**Choosing a mode:**

- Use **default mode** for simpler backup configurations (recommended)
- Use **advanced mode** if you need multiple custom buckets

Test the Installation
----------------------

1. Start the Server
~~~~~~~~~~~~~~~~~~~

Open a terminal and start the pys3local server:

.. code-block:: bash

   # Start with no authentication (for testing)
   pys3local serve --no-auth --debug

You should see output like::

   Data directory: /tmp/s3store
   Authentication disabled
   Note: Clients can use any credentials when auth is disabled

   Starting S3 server at http://0.0.0.0:10001/

   rclone configuration:
   Add this to ~/.config/rclone/rclone.conf:

   [pys3local]
   type = s3
   provider = Other
   access_key_id = test
   secret_access_key = test
   endpoint = http://localhost:10001
   region = us-east-1

   Press Ctrl+C to stop the server

**Important:** The server shows you the exact configuration needed for rclone!
Copy the configuration block into your ``~/.config/rclone/rclone.conf`` file.

2. Test with boto3 (Python)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In a **new terminal**, run the test script:

.. code-block:: bash

   # If you have boto3 installed
   python3 /tmp/test_pys3local.py

Or test manually:

.. code-block:: python

   import boto3

   # Create client
   s3 = boto3.client(
       's3',
       endpoint_url='http://localhost:10001',
       aws_access_key_id='test',
       aws_secret_access_key='test'
   )

   # Create bucket
   s3.create_bucket(Bucket='default')  # In default mode, use "default" bucket

   # Upload file
   s3.put_object(Bucket='default', Key='test.txt', Body=b'Hello!')

   # List objects
   print(s3.list_objects_v2(Bucket='default'))

**Note:** In default mode, always use "default" as the bucket name. In advanced mode
(with ``--allow-bucket-creation``), you can create custom buckets like 'mybucket'.

3. Test with curl
~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # List buckets (shows "default" in default mode)
   curl http://localhost:10001/

   # Create bucket (use "default" in default mode)
   curl -X PUT http://localhost:10001/default

   # Upload object
   echo "Hello, World!" | curl -X PUT http://localhost:10001/default/hello.txt --data-binary @-

   # List objects in bucket
   curl http://localhost:10001/default

   # Get object
   curl http://localhost:10001/default/hello.txt

4. Test with rclone
~~~~~~~~~~~~~~~~~~~

Configure rclone:

.. code-block:: bash

   # Create config
   mkdir -p ~/.config/rclone
   cat >> ~/.config/rclone/rclone.conf << EOF
   [pys3local]
   type = s3
   provider = Other
   access_key_id = test
   secret_access_key = test
   endpoint = http://localhost:10001
   region = us-east-1
   EOF

Test it:

.. code-block:: bash

   # List buckets (shows "default" in default mode)
   rclone lsd pys3local:

   # In default mode, use "default" bucket
   rclone mkdir pys3local:default

   # Copy a file
   echo "test data" > /tmp/testfile.txt
   rclone copy /tmp/testfile.txt pys3local:default/

   # List files
   rclone ls pys3local:default/

   # Download file
   rclone copy pys3local:default/testfile.txt /tmp/downloaded.txt
   cat /tmp/downloaded.txt

**Advanced mode example:**

If you started the server with ``--allow-bucket-creation``, you can create custom buckets:

.. code-block:: bash

   # Create custom bucket (only in advanced mode)
   rclone mkdir pys3local:rclone-test

   # Use it
   rclone copy /tmp/testfile.txt pys3local:rclone-test/
   rclone ls pys3local:rclone-test/

Example: Backup with rclone
----------------------------

**Default mode (recommended):**

.. code-block:: bash

   # Start server with persistent storage (default mode)
   pys3local serve --path /srv/s3-backups --access-key-id mykey --secret-access-key mysecret

   # In another terminal, configure rclone with the credentials
   cat >> ~/.config/rclone/rclone.conf << EOF
   [backup]
   type = s3
   provider = Other
   access_key_id = mykey
   secret_access_key = mysecret
   endpoint = http://localhost:10001
   region = us-east-1
   EOF

   # Use the "default" bucket - no need to create it
   rclone sync ~/Documents backup:default/documents

   # List backups
   rclone tree backup:default

   # Restore files
   rclone sync backup:default/documents ~/Documents-restored

**Advanced mode (custom buckets):**

.. code-block:: bash

   # Start server with custom bucket support
   pys3local serve --path /srv/s3-backups --allow-bucket-creation \
       --access-key-id mykey --secret-access-key mysecret

   # Create backup bucket
   rclone mkdir backup:daily-backups

   # Backup your home directory (or any directory)
   rclone sync ~/Documents backup:daily-backups/documents

   # List backups
   rclone tree backup:daily-backups

   # Restore files
   rclone sync backup:daily-backups/documents ~/Documents-restored

Configuration Examples
----------------------

Local Storage with Authentication
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   pys3local serve \
       --path /srv/s3data \
       --access-key-id production-key \
       --secret-access-key production-secret \
       --listen 0.0.0.0:10001

Using Backend Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Configure backend
   pys3local config
   # Choose: Add backend
   # Name: local-backup
   # Type: local
   # Path: /srv/backups

   # Use it
   pys3local serve --backend-config local-backup

Running in Background
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Using nohup
   nohup pys3local serve --path /srv/s3 > /tmp/pys3local.log 2>&1 &

   # Check if running
   curl http://localhost:10001/

   # Stop
   pkill -f pys3local

Troubleshooting
---------------

Check if server is running
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Test connection
   curl http://localhost:10001/

   # Or with boto3
   python3 -c "import boto3; s3 = boto3.client('s3', endpoint_url='http://localhost:10001', aws_access_key_id='test', aws_secret_access_key='test'); print(s3.list_buckets())"

View logs
~~~~~~~~~

If you started with ``--debug``, you'll see detailed logs in the terminal.

Permission errors
~~~~~~~~~~~~~~~~~

Make sure the data directory is writable:

.. code-block:: bash

   mkdir -p /tmp/s3store
   chmod 755 /tmp/s3store

Using Drime Backend
-------------------

If you're using the Drime Cloud backend, pys3local automatically manages an MD5 cache:

.. code-block:: bash

   # Configure Drime backend
   export DRIME_API_KEY="your-api-key"
   pys3local serve --backend drime

   # View cache statistics
   pys3local cache stats

   # Clean cache for a workspace
   pys3local cache cleanup --workspace 1465

Limiting S3 Scope with Root Folder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can limit S3 operations to a specific folder in your Drime workspace:

.. code-block:: bash

   # Limit S3 to a specific folder
   pys3local serve --backend drime --root-folder "backups/s3" --no-auth

   # Save root_folder in backend configuration
   pys3local config
   # When adding Drime backend, specify root folder: "backups/s3"

   # Use saved configuration
   pys3local serve --backend-config mydrime --no-auth

**How it works:**

- When you specify ``--root-folder "backups/s3"``:

  - S3 buckets are created as folders within ``backups/s3/``
  - Listing buckets shows folders in ``backups/s3/`` only
  - All object operations are relative to ``backups/s3/``

- The root folder is automatically created if it doesn't exist
- Works with nested paths: ``--root-folder "backups/s3/prod"``

**Use cases:**

- Dedicate a specific folder for S3 backups
- Share a workspace with other applications
- Create separate environments (dev/staging/prod)

**Example with rclone:**

.. code-block:: bash

   # Start server with root folder
   pys3local serve --backend drime --root-folder "backups/rclone" --no-auth

   # In another terminal
   rclone lsd pys3local:              # Lists folders in backups/rclone/
   rclone mkdir pys3local:mybucket    # Creates backups/rclone/mybucket/
   rclone copy /data pys3local:mybucket/

See :doc:`cache_management` for complete cache management documentation.

Next Steps
----------

- Read the :doc:`index` for complete documentation
- Check :doc:`installation` for advanced setup
- Learn about :doc:`cache_management` for Drime backend
- Review examples in ``tests/test_local_provider.py``
- Configure for production use with authentication
- Set up as a systemd service (see :doc:`installation`)
