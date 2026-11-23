"""Existing x.bat credentials imported as server-side license records.

The values below are salted PBKDF2 verification hashes from the original
launcher. The plaintext developer/admin credentials were never present in the
source; they remain usable only if the holder knows them. The user key
``KBMTI-USRMP-1304`` is the one credential documented as confirmed for testing.
"""

LEGACY_LICENSES = (
    {
        "id": "legacy-dev",
        "role": "DEVELOPER",
        "key_salt": "KBMTI::DEV",
        "key_hash": "0b50080e5aa8dad839b17109dea3f270df6c8348be29bf290564090fe06a27dc",
        "key_algo": "sha1",
        "key_iterations": 150000,
        "admin_salt": None,
        "admin_hash": None,
        "admin_algo": None,
        "admin_iterations": None,
        "note": "Imported from the original x.bat developer hash.",
    },
    {
        "id": "legacy-user",
        "role": "USER",
        "key_salt": "KBMTI::USR",
        "key_hash": "622cbd0571f53c4da9f3b53b078dbeadcce527485742e366c07bd255ceceba6f",
        "key_algo": "sha1",
        "key_iterations": 150000,
        "admin_salt": None,
        "admin_hash": None,
        "admin_algo": None,
        "admin_iterations": None,
        "note": "Imported from the original x.bat user hash.",
    },
    {
        "id": "legacy-admin",
        "role": "ADMIN",
        "key_salt": "KBMTI::ADMKEY",
        "key_hash": "438a567c4a60f9cfe2ac32275b2c03e8381fa971db6ebf5464e39d2bd9ca8e53",
        "key_algo": "sha1",
        "key_iterations": 150000,
        "admin_salt": "KBMTI::ADMPASS",
        "admin_hash": "237dd729c357cfdbecab5e3b2df20e6c2508aa0c17061a59f90afef1edec392f",
        "admin_algo": "sha1",
        "admin_iterations": 150000,
        "note": "Imported from the original x.bat administrator hashes.",
    },
)
