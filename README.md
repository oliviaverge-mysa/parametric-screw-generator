# Parametric Screw Head Generator

Generates parametric screw heads using CadQuery (OpenCASCADE B-Rep kernel).

## Supported Head Types

| Type     | Description                           |
|----------|---------------------------------------|
| `flat`   | Countersunk cone (apex at top)        |
| `pan`    | Cylinder + shallow spherical dome     |
| `button` | Cylinder + pronounced spherical dome  |
| `hex`    | Hexagonal prism                       |

## Coordinate Convention

- Head centered on Z axis
- Underside at Z = 0
- Head occupies Z in [0, h]

## Usage

```python
from head import make_head

solid = make_head({"type": "pan", "d": 8, "h": 4})
```

## Preview Harness

```bash
python preview.py
```

Generates individual STEP/STL files and a combined gallery STEP in `outputs/`.

## Tests

```bash
python -m pytest test_head.py -v
```

## Requirements

- Python 3.11+
- CadQuery 2.6+
