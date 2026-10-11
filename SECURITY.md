# Security model

Face Lock is a local experimental application. Its file encryption and camera access checks have different trust boundaries: encryption protects a locked archive when its key is unavailable, while the face and gesture checks are bypassable software controls on the computer holding that key.

## What encryption protects

File contents and the manifest containing filenames and directory names are encrypted using AES-256-GCM. The app generates random 256-bit vault keys and fresh nonces for encrypted records. Authentication binds records to their vault and record identifiers, and decryption rejects modified ciphertext.

The algorithm and source code are public by design. Knowing either is not sufficient to decrypt data without the key. This does not imply that the whole application is tamperproof or that its custom archive format has undergone an independent security audit.

While locked, the original folder path contains `.face-lock-vault/contents.facevault` and a state file. The outer folder name, path, state, archive structure, approximate sizes, and file count are not concealed. Treat these as observable metadata.

## What the camera gate does not protect

Vault keys are available to the app through macOS Keychain or Windows user-scoped DPAPI storage. DPAPI binds the stored secret to the Windows user profile; code running as that user may decrypt it. Moving the encrypted folder to another account or computer requires its recovery key. There is no password-derived secret or hardware-enforced biometric release policy in this prototype. Someone controlling the logged-in account, accessing the key, or modifying the program may bypass face and gesture matching. Malware on the same account and a compromised operating system are outside the protection boundary.

Landmark matching, blink/head-turn prompts, and recorded pose sequences are not certified liveness detection. Do not assume they reject photos, replayed video, virtual cameras, or other presentation attacks. The prototype has no validated biometric error rates or spoofing-resistance claims.

## Plaintext lifecycle

Unlocking restores ordinary readable files at the original folder path. Finder, File Explorer, and other programs can access them normally. Locking encrypts their current contents and replaces them only after verification. Close editors and stop other writers before starting either operation.

The implementation stages data in temporary sibling directories, checks the result, swaps directories, and attempts cleanup. Handled failures include rollback paths, but the full operation is not an atomic transaction across crashes or power loss. Failed cleanup or interrupted operations can leave readable staging or original directories behind. A forced exit while unlocked can leave the original folder readable.

Deleting readable originals is not guaranteed secure erasure. SSD behavior, filesystem snapshots, backups, sync services, open handles, and previously exported copies may retain recoverable data. Copies made through **Save a copy elsewhere…** remain readable after locking the managed folder. Independent backups are essential, but their confidentiality is your responsibility.

## Keys and local data

The `FL1-…` recovery key contains the vault key and grants full access. Keep it privately outside the managed folder. Do not put it in screenshots, source files, logs, issue reports, or messages. If both the recovery key and stored key are lost, the app cannot recover the encrypted files.

Face and gesture templates are encrypted locally using a platform-protected profile key. Camera frames are processed in memory; application code does not save video or transmit frames to a service. Initial setup downloads Python dependencies and model assets. MediaPipe's upstream [privacy notice](https://pypi.org/project/mediapipe/1.1.0/) says its Tasks APIs send performance and utilization metrics to Google; local frame processing is not a zero-telemetry guarantee. Local settings retain the selected folder path. Encrypting stored templates does not prevent access by someone who can obtain their stored key.

Do not delete `.face-lock-vault`, including while the folder is unlocked. It contains the encrypted backing archive and management state. Keep runtime data, test vaults, recovery keys, and real camera images out of repository commits.

## Supported data and limitations

Use ordinary files in a specific data folder. Symlinks, Windows junctions, and special files are rejected. macOS resource forks and Windows alternate data streams are rejected before replacing originals. Filenames must also be valid on Windows, even when encrypting on macOS. Extended attributes, ACLs, timestamps, and original permissions are not preserved. The supported limits are 64 MiB per file, 2 GiB total file data, 2,000 files, and 2,000 directories. Do not use the prototype to transform application bundles, system folders, or a whole home directory.

Automated encryption, tampering, template, gesture-state, and folder-transaction tests are useful regression checks. UI screenshots and blank-frame inference checks do not establish live recognition accuracy or a complete security assessment.

## Reporting problems

For a non-sensitive bug, open an issue with the relevant steps, app/Python version, and a small disposable reproduction. Never attach real vault contents, biometric templates, keys, or screenshots exposing personal paths. For a security problem requiring private disclosure, request a private contact route without publishing exploit details or sensitive data in a public issue.
