Quick Start Guide
=================

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
   Starting S3 server at http://0.0.0.0:10001/

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
   s3.create_bucket(Bucket='mybucket')

   # Upload file
   s3.put_object(Bucket='mybucket', Key='test.txt', Body=b'Hello!')

   # List objects
   print(s3.list_objects_v2(Bucket='mybucket'))

3. Test with curl
~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # List buckets (should return XML)
   curl http://localhost:10001/

   # Create bucket
   curl -X PUT http://localhost:10001/mybucket

   # Upload object
   echo "Hello, World!" | curl -X PUT http://localhost:10001/mybucket/hello.txt --data-binary @-

   # List objects in bucket
   curl http://localhost:10001/mybucket

   # Get object
   curl http://localhost:10001/mybucket/hello.txt

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

   # List buckets
   rclone lsd pys3local:

   # Create bucket
   rclone mkdir pys3local:rclone-test

   # Copy a file
   echo "test data" > /tmp/testfile.txt
   rclone copy /tmp/testfile.txt pys3local:rclone-test/

   # List files
   rclone ls pys3local:rclone-test/

   # Download file
   rclone copy pys3local:rclone-test/testfile.txt /tmp/downloaded.txt
   cat /tmp/downloaded.txt

Example: Backup with rclone
----------------------------

.. code-block:: bash

   # Start server with persistent storage
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

See :doc:`cache_management` for complete cache management documentation.

Next Steps
----------

- Read the :doc:`index` for complete documentation
- Check :doc:`installation` for advanced setup
- Learn about :doc:`cache_management` for Drime backend
- Review examples in ``tests/test_local_provider.py``
- Configure for production use with authentication
- Set up as a systemd service (see :doc:`installation`)
