"""系统级工具"""
from wjx.utils.system.cleanup_runner import CleanupRunner
from wjx.utils.system.hosts_helper import (
    is_admin,
    fetch_github_hosts,
    check_hosts_status,
    update_hosts_file,
    remove_hosts_entries,
    run_hosts_operation_as_admin,
)
from wjx.utils.system.registry_manager import RegistryManager

__all__ = [
    "CleanupRunner",
    "is_admin",
    "fetch_github_hosts",
    "check_hosts_status",
    "update_hosts_file",
    "remove_hosts_entries",
    "run_hosts_operation_as_admin",
    "RegistryManager",
]
