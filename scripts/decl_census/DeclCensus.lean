import Lean

open Lean

namespace DeclCensus

/-- JSON serialization helpers -/
def escapeJsonString (s : String) : String :=
  s.replace "\"" "\\\""
    |>.replace "\\" "\\\\"
    |>.replace "\n" "\\n"
    |>.replace "\r" "\\r"
    |>.replace "\t" "\\t"

def jsonString (s : String) : String :=
  "\"" ++ escapeJsonString s ++ "\""

def jsonArray (items : List String) : String :=
  "[" ++ ", ".intercalate items ++ "]"

def jsonObject (fields : List (String × String)) : String :=
  "{" ++ ", ".intercalate (fields.map fun (k, v) => jsonString k ++ ": " ++ v) ++ "}"

/-- Collect constants referenced in an expression -/
partial def collectReferencedConstants (e : Expr) : NameSet :=
  e.foldConsts NameSet.empty fun consts n => consts.insert n

/-- Process all declarations in the environment -/
def censusAllDecls (env : Environment) : IO Unit := do
  let stdout := IO.stdout

  -- Build a mapping of constants to their defining modules
  let mut constToModule : HashMap Name Name := .empty
  for modName in env.header.moduleNames do
    if let some idx := env.getModuleIdx? modName then
      for constName in (env.getModuleConstants idx).toList do
        constToModule := constToModule.insert constName modName

  let constants := env.constants.map

  -- Process only Mathlib declarations
  for (constName, info) in constants do
    let constStr := constName.toString
    -- Filter: only Mathlib decls
    if !constStr.startsWith "Mathlib." then
      continue

    try
      -- Get defining module
      let definingMod := match constToModule.find? constName with
        | some m => m.toString
        | none => "unknown"

      -- Collect references
      let typeSig := info.type
      let sigConsts := collectReferencedConstants typeSig
      let bodyConsts := match info.value? with
        | some body => collectReferencedConstants body
        | none => NameSet.empty

      -- Find external users (declarations that reference this one)
      let mut externalUsersSig : NameSet := NameSet.empty
      let mut externalUsersBody : NameSet := NameSet.empty
      let mut intraModuleReferrers : NameSet := NameSet.empty

      for (refName, refInfo) in constants do
        let refMod := constToModule.find? refName |>.map (·.toString)
        let refTypeSig := refInfo.type
        let refBodyVal := refInfo.value?

        let refSigConsts := collectReferencedConstants refTypeSig
        if refSigConsts.contains constName then
          match refMod with
          | some m if m == definingMod =>
            intraModuleReferrers := intraModuleReferrers.insert refName
          | some m =>
            externalUsersSig := externalUsersSig.insert m
          | none => ()

        match refBodyVal with
        | some body =>
          let refBodyConsts := collectReferencedConstants body
          if refBodyConsts.contains constName then
            match refMod with
            | some m if m == definingMod =>
              intraModuleReferrers := intraModuleReferrers.insert refName
            | some m if !externalUsersSig.contains m =>
              externalUsersBody := externalUsersBody.insert m
            | _ => ()
        | none => ()

      -- Get declaration kind
      let kind := match info with
        | ConstantInfo.thmInfo _ => "theorem"
        | ConstantInfo.defInfo _ => "def"
        | ConstantInfo.axiomInfo _ => "axiom"
        | ConstantInfo.opaqueInfo _ => "opaque"
        | ConstantInfo.inductiveInfo _ => "inductive"
        | ConstantInfo.structureInfo _ => "structure"
        | ConstantInfo.classInfo _ => "class"
        | _ => "other"

      -- Build JSON output
      let externalUsersAll := externalUsersSig.union externalUsersBody
      let json := jsonObject [
        ("fq_name", jsonString constName.toString),
        ("defining_module", jsonString definingMod),
        ("kind", jsonString kind),
        ("attributes", jsonArray []),
        ("is_private", if constName.isPrivateName then "true" else "false"),
        ("is_protected", "false"),
        ("external_users_sig", jsonArray (externalUsersSig.toList.map jsonString)),
        ("external_users_body", jsonArray (externalUsersBody.toList.map jsonString)),
        ("n_external_users", toString externalUsersAll.size),
        ("intra_module_referrers", jsonArray (intraModuleReferrers.toList.map jsonString)),
        ("n_intra_module_refs", toString intraModuleReferrers.size)
      ]

      stdout.putStrLn json
    catch _ =>
      ()

end DeclCensus
