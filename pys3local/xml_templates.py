"""XML templates for S3 API responses."""

from __future__ import annotations

from typing import Any

# Error response template
ERROR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Error>
    <Code>{code}</Code>
    <Message>{message}</Message>
    <RequestId>{request_id}</RequestId>
</Error>"""

# List buckets response template
LIST_BUCKETS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ListAllMyBucketsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
    <Owner>
        <ID>pys3local</ID>
        <DisplayName>pys3local</DisplayName>
    </Owner>
    <Buckets>
        {buckets}
    </Buckets>
</ListAllMyBucketsResult>"""

BUCKET_XML = """        <Bucket>
            <Name>{name}</Name>
            <CreationDate>{creation_date}</CreationDate>
        </Bucket>"""

# List objects response template
LIST_OBJECTS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
    <Name>{name}</Name>
    <Prefix>{prefix}</Prefix>
    <Marker>{marker}</Marker>
    <MaxKeys>{max_keys}</MaxKeys>
    <IsTruncated>{is_truncated}</IsTruncated>
    {delimiter_xml}
    {contents}
    {common_prefixes}
    {next_marker_xml}
</ListBucketResult>"""

OBJECT_XML = """    <Contents>
        <Key>{key}</Key>
        <LastModified>{last_modified}</LastModified>
        <ETag>{etag}</ETag>
        <Size>{size}</Size>
        <StorageClass>{storage_class}</StorageClass>
    </Contents>"""

COMMON_PREFIX_XML = """    <CommonPrefixes>
        <Prefix>{prefix}</Prefix>
    </CommonPrefixes>"""

# Delete objects response template
DELETE_OBJECTS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DeleteResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
    {deleted}
    {errors}
</DeleteResult>"""

DELETED_OBJECT_XML = """    <Deleted>
        <Key>{key}</Key>
    </Deleted>"""

DELETE_ERROR_XML = """    <Error>
        <Key>{key}</Key>
        <Code>{code}</Code>
        <Message>{message}</Message>
    </Error>"""

# Copy object response template
COPY_OBJECT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CopyObjectResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
    <LastModified>{last_modified}</LastModified>
    <ETag>{etag}</ETag>
</CopyObjectResult>"""

# ACL response template (simplified)
ACL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<AccessControlPolicy>
    <Owner>
        <ID>pys3local</ID>
        <DisplayName>pys3local</DisplayName>
    </Owner>
    <AccessControlList>
        <Grant>
            <Grantee
                xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                xsi:type="CanonicalUser">
                <ID>pys3local</ID>
                <DisplayName>pys3local</DisplayName>
            </Grantee>
            <Permission>FULL_CONTROL</Permission>
        </Grant>
    </AccessControlList>
</AccessControlPolicy>"""


def format_error_xml(code: str, message: str, request_id: str = "pys3local") -> str:
    """Format an error response.

    Args:
        code: Error code
        message: Error message
        request_id: Request ID

    Returns:
        Formatted XML string
    """
    return ERROR_XML.format(
        code=code, message=escape_xml(message), request_id=request_id
    )


def format_list_buckets_xml(buckets: list[Any]) -> str:
    """Format a list buckets response.

    Args:
        buckets: List of Bucket objects

    Returns:
        Formatted XML string
    """
    buckets_xml = "\n".join(
        BUCKET_XML.format(
            name=escape_xml(b.name), creation_date=b.creation_date.isoformat() + "Z"
        )
        for b in buckets
    )
    return LIST_BUCKETS_XML.format(buckets=buckets_xml)


def format_list_objects_xml(
    bucket_name: str,
    prefix: str,
    marker: str,
    max_keys: int,
    is_truncated: bool,
    delimiter: str,
    contents: list[Any],
    common_prefixes: list[str],
    next_marker: str = "",
) -> str:
    """Format a list objects response.

    Args:
        bucket_name: Bucket name
        prefix: Prefix filter
        marker: Pagination marker
        max_keys: Maximum keys
        is_truncated: Whether results are truncated
        delimiter: Delimiter
        contents: List of S3Object
        common_prefixes: List of common prefixes
        next_marker: Next pagination marker

    Returns:
        Formatted XML string
    """
    contents_xml = "\n".join(
        OBJECT_XML.format(
            key=escape_xml(obj.key),
            last_modified=obj.last_modified.isoformat() + "Z",
            etag=f"&quot;{obj.etag}&quot;",
            size=obj.size,
            storage_class=obj.storage_class,
        )
        for obj in contents
    )

    common_prefixes_xml = "\n".join(
        COMMON_PREFIX_XML.format(prefix=escape_xml(p)) for p in common_prefixes
    )

    delimiter_xml = (
        f"<Delimiter>{escape_xml(delimiter)}</Delimiter>" if delimiter else ""
    )
    next_marker_xml = (
        f"<NextMarker>{escape_xml(next_marker)}</NextMarker>"
        if is_truncated and next_marker
        else ""
    )

    return LIST_OBJECTS_XML.format(
        name=escape_xml(bucket_name),
        prefix=escape_xml(prefix),
        marker=escape_xml(marker),
        max_keys=max_keys,
        is_truncated=str(is_truncated).lower(),
        delimiter_xml=delimiter_xml,
        contents=contents_xml,
        common_prefixes=common_prefixes_xml,
        next_marker_xml=next_marker_xml,
    )


def format_delete_objects_xml(deleted: list[str], errors: list[dict[str, str]]) -> str:
    """Format a delete objects response.

    Args:
        deleted: List of deleted keys
        errors: List of error dicts with keys: key, code, message

    Returns:
        Formatted XML string
    """
    deleted_xml = "\n".join(
        DELETED_OBJECT_XML.format(key=escape_xml(k)) for k in deleted
    )

    errors_xml = "\n".join(
        DELETE_ERROR_XML.format(
            key=escape_xml(e["key"]),
            code=e["code"],
            message=escape_xml(e["message"]),
        )
        for e in errors
    )

    return DELETE_OBJECTS_XML.format(deleted=deleted_xml, errors=errors_xml)


def format_copy_object_xml(last_modified: str, etag: str) -> str:
    """Format a copy object response.

    Args:
        last_modified: Last modified timestamp
        etag: Object ETag

    Returns:
        Formatted XML string
    """
    return COPY_OBJECT_XML.format(
        last_modified=last_modified, etag=f"&quot;{etag}&quot;"
    )


def escape_xml(text: str) -> str:
    """Escape special XML characters.

    Args:
        text: Text to escape

    Returns:
        Escaped text
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
