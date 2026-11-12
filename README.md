# ruler-straight-step1

This branch contains exactly one stage of mesh coarsening, isolated and
verified on its own, with nothing else in the repository.

See [`experiments/ruler_straight_step1/README.md`](experiments/ruler_straight_step1/README.md)
for what it does, how to run it, and its verified results on 5 real assets.

```bash
pip install -r requirements.txt
cd experiments/ruler_straight_step1
python3 run_step1.py <dense_input.obj/glb> <quad_dominant_remesh.obj> <out.obj>
```
