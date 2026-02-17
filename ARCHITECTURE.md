# Screw Generator Architecture (CadQuery / OCCT)

## Goal
Generate parametric screws as CAD solids with:
- Head (4 types)
- Drive recess (3 types, separate cut)
- Shaft (core cylinder + pointed tip)
- Later: thread geometry + engineering drawing output

Outputs:
- STEP (B-Rep solid)
- STL (mesh)

## Global Coordinate Conventions
All geometry is centered on the Z axis.

### Head coordinates
- Head occupies `Z in [0, h_head]`
- `Z = 0` is the shaft-attachment reference plane for most heads
- Tool face (drive start plane) is defined per head type

### Shaft coordinates (local)
- Shaft is generated with its attachment face at `Z = 0`
- Shaft length extends away from attachment face to the pointed tip
- Default shaft local orientation is transformed during assembly as needed

### Assembly expectation
Build a single watertight solid in this order:
1) build head
2) cut drive (`head - drive_cut`)
3) union shaft (`head_with_drive ∪ shaft`)

## Head Types
- `flat`: conical frustum (inverted cone), large face and cone side defined explicitly
- `pan`: cylinder + spherical cap, `r = min(d*0.25, h*0.5)`
- `button`: cylinder + more domed spherical cap, `r = min(d*0.4, h*0.8)`
- `hex`: hexagonal prism, `acrossFlats` provided or defaulted

## Drive Types
Drive is implemented as a separate cut solid:
- hex (size 3)
- phillips (size 4)
- torx (size 6)

Drive bottom profile is modeled as:
- `(drive footprint prism) ∩ (cone/frustum)`

## Shaft
No threads yet:
- minor-diameter cylinder
- pointed cone tip

Parameters:
- `d_minor`
- `L`
- `tip_len`

## Preview / Gallery Policy
Preview modules export:
- individual examples (STEP + STL)
- combined gallery STEP
- sectioned gallery STEP for recess/junction inspection

## Non-goals (current)
- No threads yet
- No standards-certified geometry yet
- No confidential data in docs or outputs

