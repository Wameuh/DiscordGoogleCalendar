"""Cross-platform filesystem permission checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BROAD_WINDOWS_PRINCIPALS: frozenset[str] = frozenset(
    {
        "Everyone",
        "BUILTIN\\Users",
        "Users",
        "Authenticated Users",
        "NT AUTHORITY\\Authenticated Users",
    }
)


@dataclass(frozen=True)
class PermissionFinding:
    """A filesystem permission issue found during validation."""

    path: Path
    severity: str
    message: str


@dataclass(frozen=True)
class WindowsAce:
    """Small adapter-friendly representation of a Windows access rule."""

    principal: str
    rights: frozenset[str]
    access_type: str = "Allow"


def check_unix_secret_mode(
    path: Path, mode: int, *, is_directory: bool
) -> tuple[PermissionFinding, ...]:
    """Check Unix-like secret file or directory permissions."""
    allowed = 0o700 if is_directory else 0o600
    permission_bits = mode & 0o777
    unsafe_bits = permission_bits & ~allowed
    if unsafe_bits == 0:
        return ()
    expected = "0700" if is_directory else "0600"
    return (
        PermissionFinding(
            path=path,
            severity="High",
            message=f"Permissions {permission_bits:04o} are broader than {expected}",
        ),
    )


def check_windows_secret_acl(
    path: Path, aces: tuple[WindowsAce, ...]
) -> tuple[PermissionFinding, ...]:
    """Check Windows ACL entries for broad read principals."""
    findings: list[PermissionFinding] = []
    read_rights = {"Read", "ReadAndExecute", "FullControl", "Modify"}
    broad_principals = {principal.casefold() for principal in BROAD_WINDOWS_PRINCIPALS}
    for ace in aces:
        if ace.access_type.lower() != "allow":
            continue
        if ace.principal.casefold() in broad_principals and ace.rights & read_rights:
            findings.append(
                PermissionFinding(
                    path=path,
                    severity="High",
                    message=f"Broad principal has read access: {ace.principal}",
                )
            )
    return tuple(findings)
