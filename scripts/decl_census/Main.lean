import Lean
import DeclCensus

open Lean

def main : IO Unit := do
  IO.eprintln "[decl_census] Importing Mathlib..."
  let env ← Lean.importModules
    [{ module := `Mathlib, runtimeOnly := false }]
    {}
    .empty

  IO.eprintln "[decl_census] Starting census of mathlib declarations..."
  DeclCensus.censusAllDecls env
  IO.eprintln "[decl_census] Census complete." 
