/-
Copyright (c) 2026 Marcelo Lynch. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: Marcelo Lynch
-/
module

public import Cache.Requests
public import Cache.Marker

/-!
# The rclone upload tool

An opt-in transfer tool: a system [rclone](https://rclone.org) against the
resolved location (`Location`), addressed through rclone's `:s3:` remote
syntax. `Cache/Upload/S3.lean` assembles the child environment that carries
the credentials and endpoint and calls `putStagedViaRclone`. The tool derives
its remote paths from the location's root.
-/

public section

namespace Cache.Requests

open System (FilePath)

/-- Split an S3 URL into its endpoint origin and bucket path. The path keeps
any prefix after the bucket, including a container segment. Upload resolution
and the rclone adapter share this validation. -/
def s3EndpointSplit (base : String) : Except String (String × String) :=
  match base.splitOn "://" with
  | [scheme, rest] =>
    match rest.splitOn "/" with
    | host :: parts =>
      if host.isEmpty || parts.isEmpty || parts.any (·.isEmpty) then
        .error s!"the upload base '{base}' does not name a bucket \
          (the s3 backend needs https://endpoint/bucket)"
      else
        .ok (s!"{scheme}://{host}", "/".intercalate parts)
    | [] => .error s!"the upload base '{base}' is not a URL"
  | _ => .error s!"the upload base '{base}' is not a URL"

/-- Whether a working rclone is available on PATH. -/
def rcloneAvailable : IO Bool := do
  try
    let out ← IO.Process.output { cmd := "rclone", args := #["version"] }
    return out.exitCode == 0
  catch _ =>
    return false

/-- The rclone flags every `put` transfer carries. `--s3-no-check-bucket`
skips the bucket-creation probe a scoped credential cannot pass. -/
def rcloneCommonFlags : Array String := #["--s3-no-check-bucket", "--retries", "5"]

/-- The concurrency of a files copy: `transfers` bounds the uploads in flight
(`--transfers`) and `checkers` bounds the existence checks in flight
(`--checkers`). -/
structure RcloneConcurrency where
  transfers : Nat := 16
  checkers : Nat := 16
  deriving Repr, BEq, Inhabited

/--
The files copy concurrency, from the raw `MATHLIB_CACHE_RCLONE_TRANSFERS` and
`MATHLIB_CACHE_RCLONE_CHECKERS` values (`transfers?`, `checkers?`). An unset
variable keeps its default. A value that is not a positive number is an
error, like the other s3 settings.

Pure so the policy is testable; `getRcloneConcurrency` wires the environment in.
-/
def rcloneConcurrencyFrom (transfers? checkers? : Option String) :
    Except String RcloneConcurrency := do
  let parse (name : String) (value? : Option String) (default : Nat) : Except String Nat :=
    match value? with
    | none => .ok default
    | some value =>
      match value.toNat? with
      | some n => if n > 0 then .ok n else .error s!"{name}={value} is not a positive number"
      | none => .error s!"{name}={value} is not a positive number"
  let defaults : RcloneConcurrency := {}
  return {
    transfers := ← parse "MATHLIB_CACHE_RCLONE_TRANSFERS" transfers? defaults.transfers
    checkers := ← parse "MATHLIB_CACHE_RCLONE_CHECKERS" checkers? defaults.checkers }

/-- Retrieves the files copy concurrency from the environment via
`rcloneConcurrencyFrom`. -/
def getRcloneConcurrency : IO RcloneConcurrency := do
  IO.ofExcept <| rcloneConcurrencyFrom
    (← getEnvNonEmpty "MATHLIB_CACHE_RCLONE_TRANSFERS")
    (← getEnvNonEmpty "MATHLIB_CACHE_RCLONE_CHECKERS")

/--
The rclone invocation for the `.ltar` files: a copy from `srcDir` into the
files prefix, restricted to the `--files-from` list, so only the files the
caller names are uploaded. The bucket path comes from `dest.root`.
A non-overwrite put passes
`--ignore-existing`, which skips objects the destination already holds; this
matches the curl tool's `If-None-Match: *`. Artifact names are content
hashes, so a skipped re-put loses nothing.

The copy does not list the destination (`--no-traverse`): the master prefix
holds millions of objects, and a listing of it costs thousands of sequential
pages per upload. The existence check is one HEAD per listed file instead,
`concurrency.checkers` at a time.
-/
def rcloneFilesArgs (dest : Location) (srcDir filesFrom : FilePath)
    (overwrite : Bool) (concurrency : RcloneConcurrency := {}) :
    Except String (Array String) := do
  let (_, bucketPath) ← s3EndpointSplit dest.root
  return #["copy", srcDir.toString, s!":s3:{bucketPath}/{dest.filesDir}",
    "--files-from", filesFrom.toString, "--no-traverse",
    "--transfers", toString concurrency.transfers,
    "--checkers", toString concurrency.checkers] ++
    (if overwrite then #[] else #["--ignore-existing"]) ++ rcloneCommonFlags

/--
The rclone invocation for the per-SHA marker: a single-file copy to the
marker path. A marker's content is the SHA that names it, so an overwrite is
safe and the copy omits `--ignore-existing`, like the curl tool's marker
put. The bucket and relative path come from the resolved marker.
-/
def rcloneMarkerArgs (marker : Location.Marker) (markerFile : FilePath) :
    Except String (Array String) := do
  let (_, bucketPath) ← s3EndpointSplit marker.root
  return #["copyto", markerFile.toString, s!":s3:{bucketPath}/{marker.path}"] ++
    rcloneCommonFlags

/--
The staged put on a system rclone. `env` carries the credentials and endpoint
from `rcloneEnv`, so no credential appears on a command line. The remote
paths come from `dest`. An invalid root fails before any transfer.
`srcDir` holds the files and `fileNames` lists the ones to upload; the list is passed as a
`--files-from` file, so only the named files are uploaded. The files are
uploaded first, `concurrency` at a time, then the marker derived by
`Location.marker?`, if present.
A files failure exits 1; a marker failure only warns (see `uploadMarker`).
The `rclone` parameter names the binary and exists for the tests; production
callers use the default.
-/
def putStagedViaRclone (dest : Location) (env : Array (String × Option String))
    (srcDir : FilePath) (fileNames : Array String) (overwrite : Bool)
    (concurrency : RcloneConcurrency := {}) (rclone : String := "rclone") : IO Unit := do
  discard <| IO.ofExcept (s3EndpointSplit dest.root)
  let run (args : Array String) : IO UInt32 := do
    let child ← IO.Process.spawn { cmd := rclone, args, env }
    child.wait
  if fileNames.isEmpty then
    IO.println "No files to upload"
  else
    IO.println s!"Uploading {fileNames.size} file(s) via rclone to \
      {dest.root}/{dest.filesDir}"
    let dir ← IO.FS.createTempDir
    let code ← try
      let filesFrom := dir / "files-from.txt"
      IO.FS.writeFile filesFrom ("\n".intercalate fileNames.toList ++ "\n")
      run (← IO.ofExcept (rcloneFilesArgs dest srcDir filesFrom overwrite concurrency))
    finally
      IO.FS.removeDirAll dir
    if code != 0 then
      IO.eprintln s!"rclone upload failed with exit code {code}"
      IO.Process.exit 1
  uploadMarker dest fun marker file => do
    let code ← run (← IO.ofExcept (rcloneMarkerArgs marker file))
    unless code == 0 do
      throw <| IO.userError s!"rclone exited with code {code}"

end Cache.Requests
