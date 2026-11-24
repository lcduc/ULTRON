### Part 1 — The paper
A. **TL;DR** — The problem is slow decoding. The idea is to draft tokens. The result is a 2.5x speedup.

B. **The problem** — Decoding one token at a time wastes the GPU.

C. **What's new** — A draft model proposes tokens (§3).

D. **How it works** — Think of a junior writer and an editor.

```
prompt -> draft model -> 4 tokens -> big model checks -> accepted tokens
```

1. The draft model proposes tokens.
2. The big model verifies them in one pass.

E. **Key equation**

$$ p_{accept} = \min\left(1, \frac{q(x)}{p(x)}\right) $$

It says a token is kept with probability q over p.

F. **How they tested it** — Table 1 lists the tasks.

G. **What the evidence shows** — 2.5x speedup on summarisation (Table 1).

### Part 2 — In practice
I. **Picture it at work** — An invented example.
