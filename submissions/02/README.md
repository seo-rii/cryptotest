# Challenge 2 submission

Files:

- `contest.c`: final portable optimized implementation using the provided harness
- `report.pdf`: required analysis, implementation, verification, and benchmark report
- `report.tex`: reproducible source for the PDF

To run the submitted harness, place the provided `testvector.txt` and `testvector_20round.txt` beside `contest.c`, then run:

```bash
gcc -O3 -Wall -Wextra -o contest contest.c
./contest
```

The repository-level reproducible reference comparison is:

```bash
python3 solutions/benchmark_02_permutation.py \
  --iterations 1000000 --repeats 9 --random-cases 100000
```
