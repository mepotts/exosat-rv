# Draft query to the corresponding author. NOT SENT.

The Nature version carries *"All correspondence and request for materials can be made to
Kevin Hoy (kevin.hoy@mail.udp.cl)"*. Kevin Hoy is also reachable at `Kevin.Hoy@eso.org`.

**Send it yourself.** Nothing in this repo should mail anyone. This draft was corrected after
M37: it does not claim an independent reproduction. It asks about the load-bearing epoch,
extraction lineage, EMPEROR setup, and order-level RVs that the public material does not settle.

---

**Subject:** Questions from a public-data audit of the CD-35 2722 B RV series

Dear Dr Hoy,

Congratulations on the CD-35 2722 B paper, and thanks for publishing the full RV table.
I have been auditing it with a separately implemented reduction starting from public CRIRES+
frames, with the aim of understanding which conclusions can transfer to other companions.

The result is more conditional than I first expected. On the 17 nights retained by an internal
across-order-spread screen, the near-171-day peak is the strongest searched period and remains
after adding BERV as a nuisance term. Restoring the eighteenth night removes that result in all
three BERV-adjusted global searches. The extraction machinery was also developed with your RV
table visible, so I do not describe this as blind or independent. My per-epoch scatter against
your Table 2 is about 70–90 m/s, and the fitted semiamplitude is 20–40% high. I would especially
value your view of the discrepant night and the effective extraction/order choices.

Now the two asks.

1. How many independent sampler runs stand behind the +2.622, and what is the scatter
among them? This is my main question, and it is not really about priors. Running the
comparison on your published Table 2 with dynesty, I found that the sampler's own
internal logZ uncertainty badly understates how much the answer moves between runs that
differ only in the random seed. Same data, same priors, same model pair: the internal
estimate says +/- 0.27, while ten independent runs scatter by 0.25 to 2.18 depending on
configuration, so a factor of 1 to 8. Raising the live points fourfold does not fix it:
the internal number shrinks as N^-1/2, to +/- 0.13, while the real scatter stays near
0.5, so the gap gets worse rather than better.

That dynesty behaviour cannot be extrapolated to EMPEROR, which I have not run. It does make
the independent-seed scatter of the reported model comparison an important reproducibility
question. A handful of EMPEROR reruns at different seeds, with the run-level evidences, would
show whether the quoted internal uncertainties also describe between-run variation.

Alongside that, the EMPEROR configuration itself would help: the priors on each
parameter (periods, amplitudes, eccentricity terms, jitter, offset), the period windows
behind the windowed evidences, and the sampler settings. On my side the one satellite
model wins under every prior family I have tried, and I would much rather run your exact
setup and find my priors were the problem than speculate. If you have the per window logZ
values for the 70, 88 and 115 day models from the Nature run, those would help too.

2. The order level RVs, before combining, for even one or two nights. My remaining
precision gap is small but stubborn, and comparing per order values would localize it
in an afternoon. Any format is fine.

Two smaller things while I have you. I reverse engineered your setup as the eleven
orders that map to oset 4,7,8,9,10,12,13,14,17,18,19 in current viper numbering, a
telluric free template built in two iterations, kappa sigma clipping at 3, and template
oversampling of 2. If any of that is wrong I would love to know. And the night at BJD
2460604.82 is in the archive but not in Table 2; my pipeline throws it out on its own
(the across order scatter is seven times the typical night), and I am guessing yours
did something similar, but it would be good to confirm.

Happy to share everything, the reduction scripts, the injection tests, the nested
sampling code, whichever is useful. And if the second satellite question resolves in
your favor with the real priors, I will be glad to have been wrong in public.

Best,

Matthew Potts

---

## Notes on the draft

- **Lead with the reproduction.** It is true, it is the strongest opener, and it makes
  clear the email is collegial rather than adversarial. The blind search result is
  M14 §6 and §8; the numbers quoted (70 to 90 m/s, 20 to 40 percent high K) are the
  per nodding and archive route figures.
- **The second satellite is now raised directly.** The old draft held it back because
  it was a BIC proxy result. That threshold was passed in M14 §1 and §7: ten dynesty
  integrals, all negative, three pairings, three prior styles. The email still frames
  it as "my priors might be the problem," which is honest (evidence is prior
  sensitive) and gives them a graceful path.
- **The asks are ordered by value.** The EMPEROR priors are the one thing we cannot
  reconstruct from any archive; order level RVs close the last precision gap. The
  config confirmation and the 60604 night are one liners they can answer from memory.
- **Not raised:** the amplitude overshoot as a claim (confound limited, M14 §9), the
  Eq. 1 metrology finding, and the v1 BJD offset (already fixed in the published
  version; leading with old nitpicks would sour the tone). The embargoed epochs
  release on their own schedule (Dec 2026 to May 2027); asking for early access in a
  first email felt like one favor too many.
