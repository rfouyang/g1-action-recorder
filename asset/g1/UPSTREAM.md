# Upstream provenance

## Canonical robot description

- Repository: https://github.com/unitreerobotics/unitree_ros
- Commit: `7d6075f7f58588b189b940130e3edab3c839b2df`
- Source directory: `robots/g1_description/`
- Source models: `g1_29dof_rev_1_0.urdf` and `g1_29dof_rev_1_0.xml`
- License: BSD-3-Clause; copied to `LICENSE`

The source model is listed by Unitree as the current 29-DOF revision 1.0
description for `mode_machine = 5`. Only meshes referenced by these two model
files are copied here. Model content is unchanged; only filenames were changed
to make the fixed fake-hand contract explicit.

## DDS joint-index reference

- Repository: https://github.com/unitreerobotics/unitree_mujoco
- Commit: `1eb6642e3f3fdfb7fb13a9794fd6a2dd93ea0e7d`
- Source: `unitree_robots/g1/g1_joint_index_dds.md`

The full Unitree MuJoCo simulator is not vendored. It remains an optional
external integration environment for later controller validation.
