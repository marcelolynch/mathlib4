/-
Copyright (c) 2025 Finn Mortimore. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: Finn Mortimore
-/
module

public import Mathlib.Order.Preorder.Chain
public import Mathlib.Data.Set.Lattice
public import Mathlib.Dynamics.FixedPoints.Basic
public import Mathlib.Order.OmegaCompletePartialOrder

/-!
# Bourbaki-Witt Theorem

This file proves the Bourbaki-Witt Theorem.

## Main definitions

- class `ChainCompletePartialOrder` : A nonempty partial order is a chain complete partial order
  such that every nonempty chain has a supremum

## Main statements

- `nonempty_fixedPoints_of_inflationary` : The Bourbaki-Witt Theorem : If $X$ is a chain complete
  partial order and $f : X → X$ is inflationary (i.e. ∀ x, x ≤ f x), then $f$ has a fixed point

## References

The proof used can be found in [serge_lang_algebra]
-/

public section

variable {α β : Type*} {ι : Sort*}

/-- The type of nonempty chains of an order -/
@[ext]
structure NonemptyChain (α : Type*) [LE α] where
  /-- The underlying set of a nonempty chain -/
  carrier : Set α
  Nonempty' : carrier.Nonempty
  isChain' : IsChain (· ≤ ·) carrier

instance {α : Type*} [LE α] : SetLike (NonemptyChain α) α where
  coe := NonemptyChain.carrier
  coe_injective' _ _ := NonemptyChain.ext

instance {α : Type*} [LE α] : PartialOrder (NonemptyChain α) := .ofSetLike (NonemptyChain α) α

/-- A chain complete partial order (CCPO) is a nonempty partial order such that every
nonempty chain has a supremum (which we call `cSup`) -/
class ChainCompletePartialOrder (α : Type*) extends PartialOrder α where
  /-- The supremum of a nonempty chain -/
  cSup : NonemptyChain α → α
  /-- `cSup` is an upper bound of the nonempty chain -/
  le_cSup (c : NonemptyChain α) (x : α) : x ∈ c.carrier → x ≤ cSup c
  /-- `cSup` is a lower bound of the set of upper bounds of the nonempty chain -/
  cSup_le (c : NonemptyChain α) (x : α) : (∀ y ∈ c.carrier, y ≤ x) → cSup c ≤ x

open ChainCompletePartialOrder Set OmegaCompletePartialOrder.Chain

namespace ChainCompletePartialOrder

instance [ChainCompletePartialOrder α] : OmegaCompletePartialOrder α where
  ωSup c := cSup (NonemptyChain.mk (range c) (range_nonempty c) (isChain_range c))
  le_ωSup _ i := le_cSup _ _ (mem_range_self i)
  ωSup_le _ _ hx := cSup_le _ _ (fun _ ⟨i, hi⟩ ↦ hi ▸ hx i)

instance [CompleteLattice α] : ChainCompletePartialOrder α where
  cSup c := sSup c
  le_cSup _ _ hx := le_sSup hx
  cSup_le _ _ h := sSup_le h

variable [ChainCompletePartialOrder α] {x : α} {f : α → α}

/-- An admissible set for given `x : α` and `f : α → α` has `x`, the base point, as a least element
and is closed under applying `f` and `cSup`. -/
structure IsAdmissible (x : α) (f : α → α) (s : Set α) : Prop where
  /-- The base point is the least element of an admissible set -/
  base_isLeast : IsLeast s x
  /-- The image of an admissible set under `f` is a subset of itself -/
  image_self_subset_self : f '' s ⊆ s
  /-- If a chain is a subset of an admissible set, its `cSup` is a member of the admissible set -/
  cSup_mem : ∀ (c : NonemptyChain α), ↑c ⊆ s → cSup c ∈ s

private lemma ici_isAdmissible (le_map : ∀ x, x ≤ f x) : IsAdmissible x f (Ici x) where
  base_isLeast := ⟨le_refl x, fun _ h ↦ h⟩
  image_self_subset_self := by
    rintro _ ⟨y, hy, rfl⟩
    exact le_trans hy (le_map _)
  cSup_mem := by
    intro c hc
    have ⟨y, hy⟩ := c.Nonempty'
    exact le_trans (hc hy) (le_cSup _ _ hy)

/-- The bottom admissible set with base point `x` and inflationary function `f` -/
abbrev bot (x : α) (f : α → α) : Set α := ⋂₀ {s | IsAdmissible x f s}

private lemma bot_isAdmissible (le_map : ∀ x, x ≤ f x) : IsAdmissible x f (bot x f) where
  base_isLeast := by
    constructor
    · exact fun _ h ↦ h.base_isLeast.1
    · intro y hy
      exact hy (Ici x) (ici_isAdmissible le_map)
  image_self_subset_self := by
    rintro _ ⟨y, hy, rfl⟩ s hs
    exact hs.image_self_subset_self ⟨y, ⟨mem_sInter.1 hy _ hs, rfl⟩⟩
  cSup_mem := by
    intro c hc s hs
    exact hs.cSup_mem c (subset_trans hc (sInter_subset_of_mem hs))

private lemma subset_bot_iff {s : Set α} (h : IsAdmissible x f s) : s ⊆ bot x f ↔ s = bot x f where
  mp h' := subset_antisymm h' (sInter_subset_of_mem h)
  mpr h' := h' ▸ subset_refl (bot x f)

private lemma map_mem_bot {y : α} (le_map : ∀ x, x ≤ f x) (h : y ∈ bot x f) : f y ∈ bot x f :=
  (bot_isAdmissible le_map).image_self_subset_self <| mem_image_of_mem f h

/-- `y` is an extreme point for `x : α` and `f : α → α` if it is in the bottom admissible set and
`y` is larger than `f z` for any `z < y` in the bottom admissible set.
This definition comes from [serge_lang_algebra] -/
structure IsExtremePt (x : α) (f : α → α) (y : α) : Prop where
  mem_bot : y ∈ bot x f
  map_le_of_mem_of_lt {z : α} (h : z ∈ bot x f) (h' : z < y) : f z ≤ y

namespace IsExtremePt

/-- If `y` is an extreme point and `f` is inflationary, then there are no element between `y` and
`f y`. -/
private lemma bot_eq_of_le_or_map_le {y : α} (le_map : ∀ x, x ≤ f x) (hy : IsExtremePt x f y) :
    {z ∈ bot x f | z ≤ y ∨ f y ≤ z} = bot x f := by
  rw [← subset_bot_iff]
  · apply sep_subset
  · apply IsAdmissible.mk
    · constructor
      · constructor
        · exact (bot_isAdmissible le_map).base_isLeast.1
        · exact Or.inl ((bot_isAdmissible le_map).base_isLeast.2 hy.mem_bot)
      · exact fun y h ↦ (bot_isAdmissible le_map).base_isLeast.2 h.1
    · rintro _ ⟨z, ⟨hz, (hzy | hyz)⟩, rfl⟩ <;>
        refine ⟨map_mem_bot le_map hz, ?_⟩
      · rcases le_iff_lt_or_eq.1 hzy with (hzy | rfl)
        · left; exact hy.map_le_of_mem_of_lt hz hzy
        · right; exact le_refl _
      · right; exact le_trans hyz (le_map z)
    · intro c hc
      refine ⟨(bot_isAdmissible le_map).cSup_mem _ (subset_trans hc (sep_subset _ _)), ?_⟩
      · by_cases! h : ∀ z ∈ c, z ≤ y
        · left; apply cSup_le c y h
        · rcases h with ⟨z, hz, hzy⟩
          have h' := Or.resolve_left (hc hz).2 hzy
          right
          apply le_trans h' (le_cSup _ _ hz)

private lemma setOf_isExtremePt_isAdmissible (le_map : ∀ x, x ≤ f x) :
    IsAdmissible x f {y | IsExtremePt x f y} := by
  apply IsAdmissible.mk
  · constructor
    · refine ⟨(bot_isAdmissible le_map).base_isLeast.1, ?_⟩
      intro y hy hyx
      exfalso
      exact lt_irrefl x (lt_of_le_of_lt ((bot_isAdmissible le_map).base_isLeast.2 hy) hyx)
    · exact fun y h ↦ (bot_isAdmissible le_map).base_isLeast.2 h.1
  · rintro _ ⟨y, hy, rfl⟩
    refine ⟨map_mem_bot le_map hy.mem_bot, ?_⟩
    intro z hz hzy
    have hz' := hz
    rw [← bot_eq_of_le_or_map_le le_map hy] at hz'
    rcases hz' with ⟨_, (hz' | hz')⟩
    · rcases le_iff_lt_or_eq.1 hz' with (hz' | rfl)
      · exact le_trans (hy.map_le_of_mem_of_lt hz hz') (le_map y)
      · exact le_refl (f z)
    · exfalso
      exact lt_irrefl z (lt_of_lt_of_le hzy hz')
  · intro c hc
    refine ⟨(bot_isAdmissible le_map).cSup_mem _ (subset_trans hc (fun _ h ↦ h.mem_bot)), ?_⟩
    intro y hy hy'
    obtain ⟨z, hz, hzy⟩ : ∃ z ∈ c, ¬ (f z ≤ y) := by
      by_contra! h
      apply lt_irrefl y (lt_of_lt_of_le hy' ?_)
      apply cSup_le
      intro z hz
      exact le_trans (le_map z) (h z hz)
    have h : y ≤ z := by
      rw [← bot_eq_of_le_or_map_le le_map (hc hz)] at hy
      exact Or.resolve_right hy.2 hzy
    obtain hyz | rfl := le_iff_lt_or_eq.1 h
    · exact le_trans ((hc hz).map_le_of_mem_of_lt hy hyz) (le_cSup _ _ hz)
    · have hc' := (bot_isAdmissible le_map).cSup_mem _ (subset_trans hc fun _ h ↦ h.mem_bot)
      rw [← bot_eq_of_le_or_map_le le_map (hc hz)] at hc'
      apply hc'.2.resolve_left
      intro hc'
      exact lt_irrefl y (lt_of_lt_of_le hy' hc')

private lemma setOf_isExtremePt_eq_bot (le_map : ∀ x, x ≤ f x) : {y | IsExtremePt x f y} = bot x f := by
  rw [← subset_bot_iff]
  · exact fun _ h ↦ h.mem_bot
  · exact setOf_isExtremePt_isAdmissible le_map

private lemma mem_bot_iff_isExtremePt {y : α} (le_map : ∀ x, x ≤ f x) :
    y ∈ bot x f ↔ IsExtremePt x f y := by
  rw [← setOf_isExtremePt_eq_bot le_map, mem_setOf]

private lemma bot_isChain (le_map : ∀ x, x ≤ f x) : IsChain (· ≤ ·) (bot x f) := by
  intro y hy z hz _
  rw [mem_bot_iff_isExtremePt le_map] at hy
  rw [← bot_eq_of_le_or_map_le le_map hy] at hz
  obtain ⟨_, (hz | hz)⟩ := hz
  · right; exact hz
  · left; exact le_trans (le_map y) hz

end IsExtremePt

open Function IsExtremePt

/- **The Bourbaki-Witt Theorem**: If `α` is a chain complete partial order and `f : α → α` is
inflationary, then `f` has a fixed point -/
private theorem nonempty_fixedPoints_of_inflationary [Nonempty α] (le_map : ∀ x, x ≤ f x) :
    (fixedPoints f).Nonempty := by
  let x : α := Classical.ofNonempty
  let y := cSup
    (NonemptyChain.mk (bot x f) ⟨x, (bot_isAdmissible le_map).base_isLeast.1⟩ (bot_isChain le_map))
  use y
  apply le_antisymm (le_cSup _ _ (_ : f y ∈ bot x f)) (le_map y)
  apply (bot_isAdmissible le_map).image_self_subset_self
  use y
  exact ⟨(bot_isAdmissible le_map).cSup_mem _ (subset_refl _), rfl⟩

end ChainCompletePartialOrder

open OmegaCompletePartialOrder

namespace CompleteLattice

variable [OmegaCompletePartialOrder α] [CompleteLattice β] {f g : α → β}

lemma ωScottContinuous.iSup {f : ι → α → β} (hf : ∀ i, ωScottContinuous (f i)) :
    ωScottContinuous (⨆ i, f i) := by
  refine ωScottContinuous.of_monotone_map_ωSup
    ⟨Monotone.iSup fun i ↦ (hf i).monotone, fun c ↦ eq_of_forall_ge_iff fun a ↦ ?_⟩
  simp +contextual [ωSup_le_iff, (hf _).map_ωSup, @forall_comm ι]

lemma ωScottContinuous.sSup {s : Set (α → β)} (hs : ∀ f ∈ s, ωScottContinuous f) :
    ωScottContinuous (sSup s) := by
  rw [sSup_eq_iSup]; apply ωScottContinuous.iSup fun f ↦ ωScottContinuous.iSup <| hs f

lemma ωScottContinuous.sup (hf : ωScottContinuous f) (hg : ωScottContinuous g) :
    ωScottContinuous (f ⊔ g) := by
  rw [← sSup_pair]
  apply ωScottContinuous.sSup
  rintro f (rfl | rfl | _) <;> assumption

lemma ωScottContinuous.top : ωScottContinuous (⊤ : α → β) :=
  ωScottContinuous.of_monotone_map_ωSup
    ⟨monotone_const, fun c ↦ eq_of_forall_ge_iff fun a ↦ by simp⟩

lemma ωScottContinuous.bot : ωScottContinuous (⊥ : α → β) := by
  rw [← sSup_empty]; exact ωScottContinuous.sSup (by simp)

end CompleteLattice

namespace CompleteLattice

variable [OmegaCompletePartialOrder α] [CompleteLinearOrder β] {f g : α → β}

-- TODO Prove this result for `ScottContinuousOn` and deduce this as a special case
-- Also consider if it holds in greater generality (e.g. finite sets)
-- N.B. The Scott Topology coincides with the Upper Topology on a Complete Linear Order
-- `Topology.IsScott.scott_eq_upper_of_completeLinearOrder`
-- We have that the product topology coincides with the upper topology
-- https://github.com/leanprover-community/mathlib4/pull/12133
lemma ωScottContinuous.inf (hf : ωScottContinuous f) (hg : ωScottContinuous g) :
    ωScottContinuous (f ⊓ g) := by
  refine ωScottContinuous.of_monotone_map_ωSup
    ⟨hf.monotone.inf hg.monotone, fun c ↦ eq_of_forall_ge_iff fun a ↦ ?_⟩
  simp only [Pi.inf_apply, hf.map_ωSup c, hg.map_ωSup c, inf_le_iff, ωSup_le_iff, Chain.coe_map,
    Function.comp, OrderHom.coe_mk, ← forall_or_left, ← forall_or_right]
  exact ⟨fun h _ ↦ h _ _, fun h i j ↦
    (h (max j i)).imp (le_trans <| hf.monotone <| c.mono <| le_max_left _ _)
      (le_trans <| hg.monotone <| c.mono <| le_max_right _ _)⟩

end CompleteLattice
