<div align="center">

# PyCraft

### A Python-powered voxel sandbox

Explore a block-based world, shape the environment, and experiment with a custom Python game.

<p>
  <img src="https://img.shields.io/badge/Python-3.x-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Rendering-OpenGL-5586A4?style=for-the-badge&logo=opengl&logoColor=white" alt="OpenGL">
  <img src="https://img.shields.io/badge/Status-In%20Development-yellow?style=for-the-badge" alt="In development">
</p>

</div>

---

## About

PyCraft is a Minecraft-inspired voxel sandbox written in Python. It uses Pygame for windowing and input, ModernGL for 3D rendering, and a chunk-based world representation to render and interact with a block environment.

The project is developed as an independent game project. Its source is available for inspection under the terms of the repository's proprietary license.

## Features

- First-person exploration in a voxel world
- Block breaking, placement, and block picking
- Creative inventory and hotbar
- Optional flight and third-person camera
- In-game debug overlay
- Chunk-based world rendering and visibility optimizations
- Screenshot and self-test command-line options

## Technology

| Component | Technology |
| --- | --- |
| Language | Python |
| Windowing and input | Pygame |
| 3D graphics | ModernGL / OpenGL |
| Numerical operations | NumPy |
| Image and texture loading | Pillow |

## Getting Started

### Requirements

- Python 3
- A graphics device with compatible OpenGL drivers
- Windows or another environment capable of running the required Python and OpenGL dependencies

### Installation

Clone the repository:

```bash
git clone https://github.com/ilter2014/PyCraft.git
cd PyCraft
```

Install the dependencies:

```bash
python -m pip install pygame moderngl numpy pillow
```

Run PyCraft:

```bash
python app.py
```

### Optional commands

Run the built-in self-test:

```bash
python app.py --selftest
```

Capture a screenshot:

```bash
python app.py --screenshot shot.png
```

## Controls

| Action | Control |
| --- | --- |
| Move | W, A, S, D |
| Look around | Mouse |
| Jump | Space |
| Sprint / descend while flying | Shift |
| Toggle flight | F |
| Break block | Left mouse button |
| Place block | Right mouse button |
| Pick block | Middle mouse button |
| Select hotbar slot | Mouse wheel or 1–9 |
| Open creative inventory | E |
| Toggle debug overlay | F3 |
| Toggle third-person view | F5 |
| Pause | Esc |
| Respawn | R |

## Project Structure

```text
PyCraft/
├── Assets/
│   └── block/
├── Worlds/
├── app.py
├── skin.png
├── LICENSE
└── README.md
```

## Contributing

Contributions are accepted from contributors authorized by the repository owner.

1. Create and work on a separate branch.
2. Keep changes focused and clearly described.
3. Open a pull request targeting `main`.
4. Wait for review and approval before merging.

The `main` branch is intended to remain protected. A pull request is not considered accepted until it has passed the repository's review requirements and has been merged.

## License

PyCraft is distributed under a **source-available proprietary license**, not an open-source license. You may inspect the repository and use the source only as permitted by the terms in [LICENSE](LICENSE).

All rights not expressly granted by the license are reserved.

---

<div align="center">
  <sub>PyCraft — Built with Python.</sub>
</div>
