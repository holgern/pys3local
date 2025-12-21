"""Command-line interface for pys3local."""

import logging
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional, Union

import click
import uvicorn
from rich.console import Console
from rich.logging import RichHandler

from pys3local.constants import (
    DEFAULT_ACCESS_KEY,
    DEFAULT_PORT,
    DEFAULT_REGION,
    DEFAULT_SECRET_KEY,
)

console = Console()


@click.group(invoke_without_command=True)
@click.pass_context
@click.version_option()
def cli(ctx: click.Context) -> None:
    """pys3local - Local S3 server for backup software.

    Run 'pys3local serve' to start the server.
    Run 'pys3local config' for configuration management.
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.option(
    "--path",
    default=str(Path(tempfile.gettempdir()) / "s3store"),
    help="Data directory (default: /tmp/s3store)",
)
@click.option(
    "--listen",
    default=f":{DEFAULT_PORT}",
    help=f"Listen address (default: :{DEFAULT_PORT})",
)
@click.option(
    "--access-key-id",
    default=DEFAULT_ACCESS_KEY,
    help=f"AWS access key ID (default: {DEFAULT_ACCESS_KEY})",
)
@click.option(
    "--secret-access-key",
    default=DEFAULT_SECRET_KEY,
    help=f"AWS secret access key (default: {DEFAULT_SECRET_KEY})",
)
@click.option(
    "--region",
    default=DEFAULT_REGION,
    help=f"AWS region (default: {DEFAULT_REGION})",
)
@click.option(
    "--no-auth",
    is_flag=True,
    help="Disable authentication",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging",
)
@click.option(
    "--backend",
    type=click.Choice(["local", "drime"]),
    default="local",
    help="Storage backend (default: local)",
)
@click.option(
    "--backend-config",
    default=None,
    help="Backend configuration name (from ~/.config/pys3local/backends.toml)",
)
@click.option(
    "--root-folder",
    default=None,
    help="Root folder path for Drime backend (e.g., 'backups/s3')",
)
@click.option(
    "--allow-bucket-creation",
    is_flag=True,
    help="Allow creation of custom buckets (default: only 'default' bucket allowed)",
)
def serve(
    path: str,
    listen: str,
    access_key_id: str,
    secret_access_key: str,
    region: str,
    no_auth: bool,
    debug: bool,
    backend: str,
    backend_config: Optional[str],
    root_folder: Optional[str],
    allow_bucket_creation: bool,
) -> None:
    """Start the S3-compatible server."""

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_time=False)],
    )

    logger = logging.getLogger(__name__)

    # Create storage provider based on backend
    if backend == "local":
        from pys3local.providers.local import LocalStorageProvider

        console.print(f"Data directory: {path}")

        provider = LocalStorageProvider(base_path=Path(path), readonly=False)

    elif backend == "drime":
        provider, config_info = _create_drime_provider(
            backend_config, False, root_folder
        )
        console.print("Storage backend: Drime Cloud")
        console.print(f"Workspace ID: {config_info.get('workspace_id', 0)}")
        if backend_config:
            console.print(f"Configuration: {backend_config}")
        if root_folder:
            console.print(f"Root Folder: {root_folder}")
    else:
        console.print(f"[red]Unknown backend: {backend}[/red]")
        sys.exit(1)

    # Parse listen address
    if listen.startswith(":"):
        host = "0.0.0.0"
        port = int(listen[1:])
    else:
        if ":" in listen:
            host, port_str = listen.rsplit(":", 1)
            port = int(port_str)
        else:
            host = listen
            port = DEFAULT_PORT

    # Display authentication status
    if no_auth:
        console.print("[yellow]Authentication disabled[/yellow]")
        console.print(
            "[dim]Note: Clients can use any credentials when auth is disabled[/dim]"
        )
    else:
        console.print("[green]Authentication enabled[/green]")
        console.print(f"Access Key ID: [cyan]{access_key_id}[/cyan]")
        console.print(f"Secret Access Key: [cyan]{secret_access_key}[/cyan]")
        console.print(f"Region: [cyan]{region}[/cyan]")

    # Display bucket mode
    if allow_bucket_creation:
        console.print("[yellow]Bucket mode: Advanced (custom buckets allowed)[/yellow]")
        console.print("[dim]Buckets will be created as directories in storage[/dim]")
    else:
        console.print("[green]Bucket mode: Default (virtual 'default' bucket)[/green]")
        console.print(
            "[dim]Only 'default' bucket is available "
            "(use --allow-bucket-creation for custom buckets)[/dim]"
        )

    # Create and run server
    from pys3local.server import create_s3_app

    try:
        app = create_s3_app(
            provider=provider,
            access_key=access_key_id,
            secret_key=secret_access_key,
            region=region,
            no_auth=no_auth,
            allow_bucket_creation=allow_bucket_creation,
        )

        console.print(f"\n[green]Starting S3 server at http://{host}:{port}/[/green]")

        # Show rclone configuration example
        if not no_auth:
            console.print("\n[bold]rclone configuration:[/bold]")
            console.print("[dim]Add this to ~/.config/rclone/rclone.conf:[/dim]")
            console.print()
            console.print("[pys3local]")
            console.print("type = s3")
            console.print("provider = Other")
            console.print(f"access_key_id = {access_key_id}")
            console.print(f"secret_access_key = {secret_access_key}")
            console.print(
                f"endpoint = http://{host if host != '0.0.0.0' else 'localhost'}:{port}"
            )
            console.print(f"region = {region}")
            console.print()
            console.print("[dim]# Test the connection:[/dim]")
            console.print(
                "[dim]rclone lsd pys3local:  # Should show 'default' bucket[/dim]"
            )
            console.print(
                "[dim]rclone ls pys3local:default/  "
                "# List files in default bucket[/dim]"
            )
            console.print()
        else:
            console.print("\n[bold]rclone configuration:[/bold]")
            console.print("[dim]Add this to ~/.config/rclone/rclone.conf:[/dim]")
            console.print()
            console.print("[pys3local]")
            console.print("type = s3")
            console.print("provider = Other")
            console.print("access_key_id = test")
            console.print("secret_access_key = test")
            console.print(
                f"endpoint = http://{host if host != '0.0.0.0' else 'localhost'}:{port}"
            )
            console.print(f"region = {region}")
            console.print()
            console.print("[dim]# Test the connection:[/dim]")
            console.print(
                "[dim]rclone lsd pys3local:  # Should show 'default' bucket[/dim]"
            )
            console.print(
                "[dim]rclone ls pys3local:default/  "
                "# List files in default bucket[/dim]"
            )
            console.print()

        console.print("[dim]Press Ctrl+C to stop the server[/dim]\n")

        # Configure uvicorn for better compatibility with S3 clients like rclone
        # Note: h11 backend is used automatically when httptools is not installed
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="error" if not debug else "info",
            server_header=False,  # Don't send Server header for compatibility
            timeout_keep_alive=75,  # Standard keep-alive timeout
            access_log=debug,  # Only show access log in debug mode
        )

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        logger.exception("Server error")
        sys.exit(1)


def _create_drime_provider(
    backend_config_name: Optional[str],
    readonly: bool,
    root_folder: Optional[str] = None,
) -> tuple[Any, dict[str, Any]]:
    """Create a Drime storage provider.

    Args:
        backend_config_name: Name of backend config to use
        readonly: Whether to enable readonly mode
        root_folder: Optional root folder path in Drime

    Returns:
        Tuple of (DrimeStorageProvider instance, config dict)
    """
    try:
        from pydrime import DrimeClient  # type: ignore[import-not-found]

        from pys3local.providers.drime import DrimeStorageProvider
    except ImportError:
        console.print("[red]Drime backend requires pydrime package.[/red]")
        console.print("Install with: pip install pys3local[drime]")
        sys.exit(1)

    config: dict[str, Any] = {}

    # Load config from backend config if provided
    if backend_config_name:
        from pys3local.config import get_config_manager

        config_manager = get_config_manager()
        backend_cfg = config_manager.get_backend(backend_config_name)

        if not backend_cfg:
            console.print(
                f"[red]Backend config '{backend_config_name}' not found.[/red]"
            )
            console.print("Available backends:")
            for name in config_manager.list_backends():
                console.print(f"  - {name}")
            sys.exit(1)

        if backend_cfg.backend_type != "drime":
            console.print(
                f"[red]Backend '{backend_config_name}' is not a drime backend.[/red]"
            )
            sys.exit(1)

        config = backend_cfg.get_all()

        try:
            api_key = config.get("api_key")

            if not api_key:
                console.print("[red]Drime backend config must include 'api_key'.[/red]")
                sys.exit(1)

            client = DrimeClient(api_key=api_key)
        except Exception as e:
            console.print(f"[red]Failed to initialize Drime client: {e}[/red]")
            sys.exit(1)
    else:
        # Initialize from environment
        try:
            client = DrimeClient()
            import os

            workspace_id = os.environ.get("DRIME_WORKSPACE_ID", "0")
            config["workspace_id"] = int(workspace_id)
        except Exception as e:
            console.print(f"[red]Failed to initialize Drime client: {e}[/red]")
            console.print("\nMake sure DRIME_API_KEY environment variable is set.")
            console.print("Or use --backend-config to specify a backend config.")
            sys.exit(1)

    # Get root_folder from CLI parameter or backend config
    effective_root_folder = root_folder or config.get("root_folder")

    provider = DrimeStorageProvider(
        client=client,
        workspace_id=config.get("workspace_id", 0),
        readonly=readonly,
        root_folder=effective_root_folder,
    )
    return provider, config


@cli.command()
@click.argument("password", required=False)
def obscure(password: Optional[str]) -> None:
    """Obscure a password for use in the pys3local config file.

    If PASSWORD is not provided, will prompt for it interactively.
    """
    from vaultconfig import obscure as obscure_module  # type: ignore[import-not-found]

    if password is None:
        password = click.prompt("Enter password to obscure", hide_input=True)

    if not password:
        console.print("[red]Error: Password cannot be empty[/red]")
        sys.exit(1)

    obscured = obscure_module.obscure(password)
    console.print(f"\n[green]Obscured password:[/green] {obscured}")
    console.print("\n[yellow]Note:[/yellow] This can be used in the config file.")
    console.print(
        "The password will be automatically revealed when the config is loaded."
    )


@cli.command()
def config() -> None:
    """Enter an interactive configuration session."""
    from pys3local.config import get_config_manager

    config_manager = get_config_manager()

    console.print("\n[bold cyan]pys3local Configuration Manager[/bold cyan]\n")

    while True:
        console.print("[bold]Available commands:[/bold]")
        console.print("  1. List backends")
        console.print("  2. Add backend")
        console.print("  3. Show backend")
        console.print("  4. Remove backend")
        console.print("  5. Exit")

        choice = click.prompt("\nEnter choice", type=int, default=5)

        if choice == 1:
            # List backends
            backends = config_manager.list_backends()
            if not backends:
                console.print("\n[yellow]No backends configured[/yellow]\n")
            else:
                console.print("\n[bold]Configured backends:[/bold]")
                for name in backends:
                    backend = config_manager.get_backend(name)
                    if backend:
                        console.print(f"  • {name} ({backend.backend_type})")
                console.print()

        elif choice == 2:
            # Add backend
            console.print("\n[bold]Add new backend[/bold]")
            name = click.prompt("Backend name")
            backend_type = click.prompt(
                "Backend type", type=click.Choice(["local", "drime"])
            )

            config_data: dict[str, Any] = {}

            if backend_type == "local":
                path = click.prompt("Base path")
                config_data["path"] = path

            elif backend_type == "drime":
                api_key = click.prompt("Drime API key", hide_input=True)
                workspace_id = click.prompt(
                    "Workspace ID (0 for personal)", type=int, default=0
                )
                root_folder = click.prompt(
                    "Root folder (optional - limit S3 scope to specific folder)",
                    default="",
                    show_default=False,
                )
                config_data["api_key"] = api_key
                config_data["workspace_id"] = workspace_id
                if root_folder:
                    config_data["root_folder"] = root_folder

            config_manager.add_backend(name, backend_type, config_data)
            console.print(f"\n[green]✓[/green] Backend '{name}' added successfully\n")

        elif choice == 3:
            # Show backend
            name = click.prompt("\nBackend name")
            backend = config_manager.get_backend(name)

            if not backend:
                console.print(f"\n[red]Error:[/red] Backend '{name}' not found\n")
            else:
                console.print(f"\n[bold]Backend: {name}[/bold]")
                console.print(f"Type: {backend.backend_type}")
                console.print("\nConfiguration:")
                config_data = backend.get_all()
                for key, value in config_data.items():
                    if key in ("api_key", "password", "secret_access_key"):
                        console.print(f"  {key}: [dim]<hidden>[/dim]")
                    else:
                        console.print(f"  {key}: {value}")
                console.print()

        elif choice == 4:
            # Remove backend
            name = click.prompt("\nBackend name")
            if config_manager.has_backend(name):
                if click.confirm(f"Remove backend '{name}'?"):
                    config_manager.remove_backend(name)
                    console.print(f"\n[green]✓[/green] Backend '{name}' removed\n")
            else:
                console.print(f"\n[red]Error:[/red] Backend '{name}' not found\n")

        elif choice == 5:
            console.print("\nExiting configuration manager.\n")
            break


@cli.group()
def cache() -> None:
    """Manage metadata cache for local storage backend.

    The cache stores object metadata in SQLite for efficient access.
    """
    pass


@cache.command(name="stats")
@click.option(
    "--bucket",
    type=str,
    default=None,
    help="Show stats for specific bucket (default: all buckets)",
)
def cache_stats(bucket: Optional[str]) -> None:
    """Show cache statistics for local storage."""
    from pys3local.metadata_db import MetadataDB

    db = MetadataDB()

    if bucket is None:
        # Show stats for all buckets
        buckets = db.list_local_buckets()

        if not buckets:
            console.print("[yellow]Cache is empty[/yellow]")
            return

        console.print("\n[bold cyan]Local Storage Cache Statistics[/bold cyan]\n")

        # Overall stats
        overall_stats = db.get_local_stats()
        console.print("[bold]Overall Statistics:[/bold]")
        console.print(f"  Total objects: {overall_stats['total_objects']:,}")
        console.print(f"  Total size: {_format_size(overall_stats['total_size'])}")

        # Per-bucket stats
        console.print("\n[bold]Per-Bucket Statistics:[/bold]")
        for bucket_name in buckets:
            bucket_stats = db.get_local_stats(bucket_name)
            console.print(f"\n  {bucket_name}:")
            console.print(f"    Objects: {bucket_stats['total_objects']:,}")
            console.print(f"    Size: {_format_size(bucket_stats['total_size'])}")

        console.print()
    else:
        # Show stats for specific bucket
        stats = db.get_local_stats(bucket)

        if stats["total_objects"] == 0:
            console.print(f"[yellow]No cache entries for bucket '{bucket}'[/yellow]")
            return

        console.print(
            f"\n[bold cyan]Cache Statistics - Bucket '{bucket}'[/bold cyan]\n"
        )
        console.print(f"Total objects: {stats['total_objects']:,}")
        console.print(f"Total size: {_format_size(stats['total_size'])}")
        console.print()


@cache.command(name="cleanup")
@click.option(
    "--bucket",
    type=str,
    default=None,
    help="Clean cache for specific bucket",
)
@click.option(
    "--all",
    "clean_all",
    is_flag=True,
    help="Clean entire cache (requires confirmation)",
)
def cache_cleanup(bucket: Optional[str], clean_all: bool) -> None:
    """Clean cache entries for local storage.

    Examples:
      pys3local cache cleanup --bucket my-bucket
      pys3local cache cleanup --all
    """
    from pys3local.metadata_db import MetadataDB

    db = MetadataDB()

    # Validate options
    if not clean_all and bucket is None:
        console.print("[red]Error: Must specify --bucket or --all[/red]")
        sys.exit(1)

    if clean_all and bucket is not None:
        console.print("[red]Error: Cannot combine --all with --bucket[/red]")
        sys.exit(1)

    # Perform cleanup
    if clean_all:
        # Get stats before cleanup
        stats = db.get_local_stats()
        if stats["total_objects"] == 0:
            console.print("[yellow]Cache is already empty[/yellow]")
            return

        total = stats["total_objects"]
        console.print(
            f"\n[bold yellow]Warning:[/bold yellow] This will remove "
            f"{total:,} objects from the cache."
        )
        if not click.confirm("Are you sure?"):
            console.print("Aborted.")
            return

        # Clean all buckets
        buckets = db.list_local_buckets()
        total_removed = 0
        for bucket_name in buckets:
            removed = db.cleanup_local_bucket(bucket_name)
            total_removed += removed

        console.print(f"[green]✓[/green] Removed {total_removed:,} objects from cache")

    elif bucket:
        # Clean specific bucket
        removed = db.cleanup_local_bucket(bucket)
        if removed == 0:
            console.print(f"[yellow]No entries found for bucket '{bucket}'[/yellow]")
        else:
            console.print(
                f"[green]✓[/green] Removed {removed:,} objects for bucket '{bucket}'"
            )


@cache.command(name="vacuum")
def cache_vacuum() -> None:
    """Optimize database and reclaim unused space.

    This should be run after large deletions to reduce database file size.
    """
    import os

    from pys3local.metadata_db import MetadataDB

    db = MetadataDB()

    # Get size before vacuum
    size_before = os.path.getsize(db.db_path) if db.db_path.exists() else 0

    console.print("Optimizing cache database...")
    db.vacuum()

    # Get size after vacuum
    size_after = os.path.getsize(db.db_path) if db.db_path.exists() else 0

    saved = size_before - size_after
    console.print("[green]✓[/green] Database optimized")
    console.print(f"  Before: {_format_size(size_before)}")
    console.print(f"  After: {_format_size(size_after)}")
    if saved > 0:
        console.print(f"  Saved: {_format_size(saved)}")


def _format_size(size_bytes: Union[int, str, None]) -> str:
    """Format size in bytes to human-readable format.

    Args:
        size_bytes: Size in bytes (None will be treated as 0)

    Returns:
        Human-readable size string
    """
    if size_bytes is None:
        return "0 B"
    # Convert to int first (handles both int and str)
    size_int = int(size_bytes) if isinstance(size_bytes, str) else size_bytes
    size: float = float(size_int)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
