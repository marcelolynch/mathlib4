import Lean
import DeclCensus

open Lean

/-- Entry point: load mathlib, run the census, stream JSONL. -/
unsafe def main : IO Unit := do
  initSearchPath (← findSysroot)
  Lean.enableInitializersExecution
  IO.eprintln "[census] importing Mathlib..."
  withImportModules #[{ module := `Mathlib }] {} (trustLevel := 1024) fun env => do
    IO.eprintln s!"[census] mathlib loaded ({env.header.moduleNames.size} modules)"
    DeclCensus.run env
