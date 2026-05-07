import Lake

open Lake DSL

package "decl_census"

require mathlib from "../.."

lean_lib DeclCensus

@[default_target]
lean_exe decl_census where
  root := `Main
