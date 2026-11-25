# Reader evidence for Cael — source, not binary execution

## Elliott JSON

Exact specimen format: `canticle-cassette-authoring-draft`, integer version0. Source fixtures and checked normalized output snapshots are under `tests/capsule-import/fixtures/`. `import_bytes`/`import_file` yield Capsule(id,title,sha256,source_bytes,scenes,source_format), with immutable Scene(id,title,seed,open_space). Optional metadata is retained in raw source. No cadence is encoded in these original three untimed scene seeds. Expected snapshots omit only raw source bytes; this is an adapter proposal, not a new adopted capsule format.

## Requested second source unresolved

`karmaterminal/memvid2` public API/page/raw and parent authenticated repository read returned404. That may mean inaccessible, renamed, or a different intended repository; no absence claim. Rune has now volunteered a real second-format write/read experiment; coordinate his source pin rather than duplicate it.

The accessible different repository `karmaterminal/memvid` is at `e6bd9f7b9c38cd8d5370fa0fc936ac1dcd751813`. Parent independently checked the existing local checkout HEAD and clean Git status and read these method bodies after the child investigation:

- `src/memvid/frame.rs:164`: `frame_by_id(&self, FrameId) -> Result<Frame>`. Exact IDs are stronger than URI lookup, which searches newest matching frames.
- `:216`: `blob_reader(&mut self, FrameId) -> Result<BlobReader>`; Plain encoding uses bounded file offsets, Zstd eagerly materializes canonical bytes. Apply decoded-size bounds.
- `:227`: `media_manifest(&self, FrameId) -> Result<Option<MediaManifest>>`.
- `:254`: `frame_canonical_payload(&mut self, FrameId) -> Result<Vec<u8>>`.
- `:279`: `frame_text_by_id(&mut self, FrameId) -> Result<String>` returns full text, unlike truncated previews.
- `src/memvid/lifecycle.rs:456–488`: `open_read_only` defaults through options to snapshot opening, but snapshot uses `.read(true).write(true)` on the OS handle. `allow_repair` delegates to ordinary open. Do not repair immutable input merely to make an import work.

Pinned source: https://github.com/karmaterminal/memvid/tree/e6bd9f7b9c38cd8d5370fa0fc936ac1dcd751813 . These inspected Rust interfaces are NOT a Python/Node SDK contract or proof that this is the intended memvid2. No capsule was created/read by this adapter, no SDK installed, and no binary support claimed.

An actual second-format bridge needs an agreed score root/profile and exact frame IDs, not arbitrary timeline/search hits. Byte seek is not story seek. Storage operation replay previews/checkpoints are not complete saved story performances. The writer→reader fixture should carry the same synthetic score and retain raw object digest + source-frame identities. Cael’s player owns inference/cadence/plot/rendition persistence; no second runtime belongs here.
