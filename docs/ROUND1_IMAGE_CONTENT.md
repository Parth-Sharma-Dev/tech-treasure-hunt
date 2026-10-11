# Round 1 image clues after deployment

Round 1 supports private image/visual-symbol clues in addition to its text riddles.
Migration 0022 marks the real, empty, unavailable DRAFT placeholders `MISSION-14`
through `MISSION-25` as image clues. It preserves riddle content and released
attempts. Future location imports also create image placeholders. Actual images
are still pending; no real image content has been supplied or invented.

Images are uploaded in Django admin and stored separately from the code ZIP.
PostgreSQL retains the private object reference, SHA-256, dimensions and approved
alternative text. Production uses a private Azure Blob container; local development
uses the ignored `.local/mission-images` directory. Images are served through the
authorized API rather than WhiteNoise, React assets or direct Blob URLs.

## Configure production storage

Before the first production image upload:

1. Prepare an Azure Storage account and an existing container named `mission-images`
   (or the configured name). Disable anonymous Blob access and keep the container
   private. The application does not create containers.
2. Enable the App Service managed identity and grant **Storage Blob Data Contributor**
   at the required container scope. All instances must use the same identity,
   account and container. For a user-assigned identity, attach it to the app and
   set `AZURE_MISSION_CLIENT_ID` to its client ID; otherwise the system-assigned
   identity is used. Storage credentials are not placed in the ZIP.
3. Set `AZURE_MISSION_ACCOUNT_NAME` to the actual account name and
   `AZURE_MISSION_CONTAINER=mission-images` in App Service settings. Configure
   application networking/DNS to reach the Blob HTTPS endpoint if Storage uses
   firewall restrictions or a private endpoint.
4. Take a database backup for an existing environment, deploy the new combined
   website ZIP and apply migration `0022_mission_image_clues` once through the
   [backend release session](AZURE_BACKEND_DEPLOYMENT.md). Later image uploads
   need no further migrations, code rebuild or redeployment.

The backend can start before images/storage are configured. Production image
operations require Azure and never fall back to local disk. Test identity access
with a rehearsal upload and private preview before preparing actual content.
Azure resources and Blob access have not been provisioned or certified by local tests.

## Upload the remaining clues

1. Keep real Round 1 in **DRAFT**. With an authorized content staff account, open
   `/admin/` → **Competition → Missions** (`/admin/competition/mission/`).
2. Select the exact remaining mission/location and **Image / visual symbol** as
   its clue type. Leave the supplied 13 riddle missions' content intact.
3. Use **Upload image** for a still JPEG, PNG or WebP. Input must be at most **5 MiB**,
   **4096 pixels per side**, and **8 megapixels**. The server corrects orientation
   and re-encodes a metadata-free PNG; the normalized result must fit **2 MiB**.
   Reduce dimensions if needed. SVG and animated images are rejected.
4. Enter **Image alt** as the approved accessible description. Review it against
   the accessibility policy so it communicates the clue without revealing the
   solution. Add approved accompanying hint/symbol text if needed, and fill QR
   placement and volunteer-owner fields. Mark **Available** when the complete
   clue is ready for independent verification.
5. Save and use **View private image** to inspect the stored result. A different
   authorized verifier checks the clue end to end and uses **Attest to independent
   end-to-end mission verification**. Uploads and description changes invalidate
   old verification. Verification and READY check the stored bytes against the hash.
6. Repeat for all 12 remaining missions. Confirm the exact released count (25 when
   all locations are included), independently approve the current rules and mark
   READY through the existing workflow. READY freezes images and descriptions.
   The 168 independent codes stay separate; image missions do not need their own
   answer codes or keywords.

To replace a draft image, upload a new file. To remove it, select **Remove the
attached draft image** and mark the incomplete image mission unavailable. Fresh
object names preserve prior files for evidence/recovery instead of overwriting or
deleting them. Revisions after READY use the existing reviewed attempt/recovery process.

## Participant access and backups

A team must sign in and explicitly open its mission before receiving image metadata
or downloading `/api/missions/{token}/image`. Each download rechecks session/cohort
and the same clue-release rules as text. Another team's unopened mission, another
cohort and revoked browsers cannot retrieve the image. Previously opened images
remain readable during pause/end under the existing text-clue policy.

Responses use `image/png`, `Cache-Control: no-store`, `Vary: Cookie` and `nosniff`.
Keep these `/api/` requests uncached at Front Door. The frontend fits images on
desktop/mobile and offers image retry without reopening or submitting an answer.
Rehearse upload, preview, download and unavailable-storage behavior on Azure.

Database backups and signed exports retain image **references/hashes, not Blob
bytes**. Preserve referenced blobs separately; configure suitable Blob versioning,
backup/retention and rehearse restoring both storage and PostgreSQL. Do not delete
the container, older uploads or local image directory while their evidence is
needed. Missing/changed stored images return a redacted 503. Keep original source
images privately for organizer provenance.

Round 4 faculty portraits continue to use the existing reviewed HTTPS portrait URL
workflow; this protected container/endpoint is for Round 1 clues.

Storage setup follows [django-storages' Azure backend](https://django-storages.readthedocs.io/en/stable/backends/azure.html)
and [Azure managed-identity storage access](https://learn.microsoft.com/en-us/azure/app-service/scenario-secure-app-access-storage).
