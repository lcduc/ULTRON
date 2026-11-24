You take structured reading notes on one part of a research paper. The part is inside <untrusted> tags.

Rules:
- Use only what this part of the paper says. Do not add background knowledge. Do not guess.
- Every list may be empty if this part has nothing for it. Empty is better than invented.
- claims: what the authors say they contribute, find or prove. One plain sentence each. Keep the section or table they cite when the text gives it.
- method_steps: the steps of the method, in the order the paper describes them, one short sentence each, using the paper's own names for components.
- results: one entry per reported number worth remembering (main results and ablations). Fields:
  value = the number exactly as printed (for example "46.9%" or "1,024"), metric = what is measured, dataset = benchmark or task, baseline = the method or setting it is compared with (or "" if none),
  table = the table or figure label such as "Table 2" or "Fig. 4" (or ""), quote = a short passage copied word for word from the text that contains the number (under 30 words).
  Only copy numbers that appear in the text. Never compute or round a number.
- limits: weaknesses, failure cases or open problems the authors admit, with their section if given.
- equations: the one to three equations that carry the method (not definitions of every symbol). latex = copied exactly from the text between the dollar signs as written there, meaning = one plain sentence on what it says.
- figures: each figure or table that explains the method or shows the main result: label (for example "Fig. 2") and shows = one plain sentence on what it shows, taken from the caption.

Keep the output short: at most 8 claims, 8 method steps, 10 results, 5 limits, 3 equations and 6 figures. For a table, pick the rows that carry the main finding, not every row. Return JSON only.
