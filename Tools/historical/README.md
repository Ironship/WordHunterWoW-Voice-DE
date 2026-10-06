# Historical repair helpers

`sync_repairs.py` and `restore_from_pack.py` used the old standalone
`WordHunterWoW-Voice-DE-Words` repository and an engine-local `sounds/w` copy.
They retain the original source for review of past repair runs; Git preserves
their prior paths as `Tools/sync_repairs.py` and `Tools/restore_from_pack.py`.

These are manual historical material, not current runnable pipeline commands.
Their relative ROOT/PACK paths belong to the old layout and are also affected
by their relocation here. Do not execute them in this consolidated checkout.
Current word audio lives solely in Dictionary-DE. The supported generation
wrapper and checkpoint controls are documented in the delivery folder's
`docs/GENEROWANIE-AUDIO.md`.
