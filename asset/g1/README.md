# Unitree G1 29-DOF fake-hand model

This directory contains the Unitree G1 revision 1.0 model for
`mode_machine = 5`. The model has 29 movable robot joints, a floating base, and
fixed rubber-hand geometry. It does not add finger degrees of freedom.

- `g1_29dof_fake_hand.urdf`: canonical kinematic model for Pink/Pinocchio.
- `g1_29dof_fake_hand.xml`: canonical MuJoCo model for preview and validation.
- `g1_joint_index_dds.md`: Unitree's DDS motor-index reference.
- `meshes/`: only the meshes referenced by the canonical URDF and MJCF.
- `model_metadata.json`: machine-readable model provenance and contract.
- `UPSTREAM.md`: exact upstream revisions and adaptation notes.
- `LICENSE`: upstream BSD-3-Clause license.

The two model files are renamed copies of Unitree's
`g1_29dof_rev_1_0.urdf` and `g1_29dof_rev_1_0.xml`. Their internal robot/model
names are intentionally unchanged.
