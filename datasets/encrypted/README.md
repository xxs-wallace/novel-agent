# Encrypted regression and Couple task snapshot

Snapshot date: 2026-11-19. Source repository commit: `358c28d830bc91861f8b0af1e3fb1cd548b45d03`.

`couple-regression-2026-11-19.7z` uses 7z AES-256 encryption, including encrypted
filenames. The password is supplied separately by the owner and is not recorded here.

The archive contains:

- The existing 32KB, 96KB and 120KB regression TXT inputs, plus `couple.txt`.
- Independent original and Writer SQLite backup snapshots, preserving all tables,
  rough/close reading progress, chapter summaries, character profiles, indexes and KB data.
- Couple world descriptions, outlines, scene cards, arc maps and Analyzer history.
- Three active Writer runs and one archived run, including artifacts, decisions,
  drafts, frozen versions, traces and associated web jobs/review records.
- An internal `MANIFEST.json` with file hashes, source hashes, table counts and run IDs,
  plus `RESTORE.md` with restoration boundaries.

Original database: 63 source segments, 49 chapters, 13 character profiles.
Writer database: 71 segments, 57 chapters, 20 character profiles, including continuation data.
Each database also retains its 60 fragment cards and 60 clusters.

The bundle contains 363 files. SQLite's backup API includes committed WAL contents;
volatile WAL/SHM files are not copied. Source files remain unchanged. Unrelated books,
general backup directories, browser logs and personal resumes are excluded.

## Verify and extract

From this directory, using a 7-Zip installation:

```sh
shasum -a 256 -c couple-regression-2026-11-19.7z.sha256
7z t couple-regression-2026-11-19.7z
7z x couple-regression-2026-11-19.7z -o/path/to/new-empty-directory
```

7-Zip prompts for the password. Extract into a new directory rather than overwriting
a live workspace. Historical absolute paths are preserved and must be explicitly
rebased when restoring elsewhere. Read the internal restoration instructions first.

Validation completed: archive integrity, wrong-password rejection, encrypted filenames,
decrypted file SHA-256 equality and SQLite integrity checks for both extracted databases.

The input TXT files already existed in Git history before this encrypted export.
Adding this bundle does not remove or encrypt those earlier plaintext copies.
