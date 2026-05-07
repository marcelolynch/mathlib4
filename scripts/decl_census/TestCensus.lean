import Lean

open Lean

/-- Test: process just TwoPointing declarations to validate the approach -/
def main : IO Unit := do
  IO.eprintln "[test_census] Importing Mathlib.Data.TwoPointing..."
  let env ← Lean.importModules
    [{ module := `Mathlib.Data.TwoPointing, runtimeOnly := false }]
    {}
    .empty

  let stdout := IO.stdout
  
  -- Find TwoPointing.swap decl
  match env.find? `Mathlib.Data.TwoPointing.swap with
  | some info =>
    let used := info.value?.getD (.const `sorry []) |>.collectAxioms
    stdout.putStrLn s!"TwoPointing.swap uses: {used.toList}"
  | none =>
    IO.eprintln "TwoPointing.swap not found"
    
  IO.eprintln "[test_census] Done."
