import Lean
import DeclCensus

open Lean

/-- Test entry point: load only TwoPointing + Nontrivial.Defs (small scope) for fast iteration. -/
unsafe def main : IO Unit := do
  initSearchPath (← findSysroot)
  Lean.enableInitializersExecution
  IO.eprintln "[test] importing small scope (TwoPointing + Nontrivial.Defs + Logic.Function.Basic)..."
  withImportModules
    #[ { module := `Mathlib.Data.TwoPointing }
     , { module := `Mathlib.Logic.Nontrivial.Defs }
     , { module := `Mathlib.Logic.Function.Basic } ]
    {} (trustLevel := 1024) fun env => do
    IO.eprintln s!"[test] loaded ({env.header.moduleNames.size} modules)"
    DeclCensus.run env
