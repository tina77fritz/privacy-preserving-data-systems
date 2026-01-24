$$
\boxed{
(g^*, b^*) = \arg\max_{(g,b)\in\mathcal{F}(f)} U(f,g,b)
}
$$

$$
\begin{aligned}
&\text{最大化效用函数 } U(f,g,b) \\
&\text{约束: } (g,b) \in \mathcal{F}(f)
\end{aligned}
$$

## Control Plane: Design Rationale and Conceptual Role

The Control Plane is the **policy intelligence layer** of the privacy-aware data system. Its purpose is not to execute data transformations or differential privacy mechanisms, but to *decide and codify* how those transformations must occur so that privacy, utility, and fairness objectives are met simultaneously.

### Technique Win Compared to the tranditional Defficiate Privacy(DP)

Traditional privacy systems treat privacy protection as a purely runtime concern: raw data enters a pipeline, transformations are applied, and DP noise is added at release. This architecture implicitly assumes that (1) all features are equally sensitive, (2) all use cases tolerate the same privacy–utility tradeoffs, and (3) the same anonymization strategy should be uniformly applied. In practice, none of these assumptions hold. Different features have radically different linkability risk, heterogeneity value, cardinality, sparsity, and fairness sensitivity. Applying a uniform privacy mechanism to all of them is either overly destructive (destroying signal unnecessarily) or insufficiently protective (leaving re-identification or bias risk unmitigated).

The Control Plane exists to **separate privacy reasoning from data execution**. It encodes privacy logic, utility intent, and governance constraints into machine-enforceable artifacts that the runtime plane consumes deterministically. Conceptually, it answers three foundational questions before any data flows:

1. *What representation of this feature is even permissible under privacy and policy constraints?*  
2. *At what processing boundary (Local, Shuffle, Central) can this feature be safely handled?*  
3. *At what granularity (item, cluster, aggregate) does this feature remain both useful and safe?*

Instead of hard-coding these decisions into pipelines, the Control Plane makes them **explicit, versioned, and auditable**.

---

## Core Design Principles

### 1) Privacy as a First-Class Optimization Constraint

The Control Plane treats privacy risk as a quantifiable input to system design, not an after-the-fact filter. Rather than assuming that de-identification or DP noise alone is sufficient, it models privacy risk structurally: how linkable a feature is, how unique its realizations are, how inferable sensitive attributes become when it is joined, and how much policy exposure it carries.

This risk is not binary (“allowed” vs. “forbidden”). It is *graded* across candidate granularities and boundaries. A feature may be safe at cluster level but unsafe at item level; safe under Shuffle DP but unsafe under Central DP; acceptable for training but not for delivery. The Control Plane’s role is to surface these distinctions and encode them into binding constraints.

---

### 2) Utility Is Intent-Dependent, Not Intrinsic

A feature’s value is not intrinsic to the raw signal; it depends on the modeling objective and the representation used. Item-level heterogeneity may be crucial for one task and irrelevant for another. Aggregation may dramatically reduce noise variance under DP but may also erase the very structure the model needs.

The Control Plane therefore does not treat “feature usefulness” as a scalar property. Instead, it reasons about *expected marginal utility* at different granularities and under different noise regimes. It formalizes the idea that:

> The best privacy-preserving representation is the one that maximizes downstream utility *subject to privacy and fairness constraints*.

This reframes privacy not as a compliance tax but as a design-space constraint within a structured optimization problem.

---

### 3) Boundary Selection Is a Trust Decision, Not a Mechanism Choice

Local DP, Shuffle DP, and Central DP are not interchangeable implementations of the same idea. They correspond to fundamentally different trust assumptions:

- **Local DP** assumes the server is untrusted and shifts noise to the client.
- **Shuffle DP** assumes an honest-but-curious server but relies on unlinkability amplification.
- **Central DP** assumes a trusted boundary but enforces formal release guarantees.

The Control Plane treats boundary selection as a **trust and threat-model decision**, not as a purely technical one. It explicitly binds each feature to a boundary based on its risk profile, the system’s operational trust assumptions, and the severity of downstream misuse.

This prevents architectural drift where highly sensitive features are silently processed under weaker guarantees simply because the pipeline happens to support them.

---

### 4) Granularity Is the Primary Privacy–Utility Control Knob

The system is designed around the insight that *granularity*, not just noise magnitude, is the dominant driver of both privacy risk and signal quality.

- Item-level representations maximize heterogeneity but amplify uniqueness and linkability.
- Cluster-level representations preserve structure while dramatically reducing risk.
- Aggregate-level representations minimize risk but collapse most modeling signal.

The Control Plane makes granularity a **first-class decision variable**. It does not assume that finer granularity is always better or that aggregation is always safer. Instead, it selects granularity based on:

- expected signal-to-noise ratio under the chosen DP mechanism,
- privacy risk gradients across granularities,
- fairness exposure (e.g., small-cell bias),
- stability under opt-out or missingness.

This enables systematic, principled downgrading (item → cluster → aggregate) instead of ad-hoc suppression.

---

## Conceptual Phases of the Control Plane

The Control Plane is structured into conceptual phases. These are not runtime steps but *logical responsibilities*.

---

### Phase 1 — Feature Intent Formalization

The system begins by formalizing what a feature *is supposed to mean*, not how it is computed.

This phase produces a canonical feature specification: what signal is measured, what modeling purpose it serves, what candidate dimensions might be included, and what outputs are expected. The goal is to remove ambiguity: privacy and fairness reasoning cannot be applied to an underspecified feature.

Design intent:
- Prevent silent scope creep.
- Make implicit modeling assumptions explicit.
- Bind feature semantics to downstream accountability.

---

### Phase 2 — Privacy Risk Modeling

Next, the Control Plane evaluates how risky the feature is *as a representation*, not as a raw event.

It models four structural risk dimensions:

- **Linkability**: how easily the feature can be joined with other datasets.
- **Uniqueness**: how sparse or identifying its realizations are.
- **Inferability**: how much sensitive information becomes predictable from it.
- **Policy Exposure**: how it intersects with regulatory or internal constraints.

These risks are evaluated at multiple candidate granularities and boundaries. The outcome is not a yes/no decision but a **risk surface** over the design space.

Design intent:
- Replace subjective privacy reviews with quantitative structure.
- Enable consistent comparisons across features.
- Provide audit-ready justifications.

---

### Phase 3 — Utility and Heterogeneity Estimation

In parallel, the Control Plane estimates how much modeling value the feature is expected to contribute at each candidate granularity.

This phase does not require a full model retraining loop; it relies on proxies such as:
- historical feature importance,
- expected heterogeneity,
- sparsity and opt-out behavior,
- DP noise amplification effects,
- downstream loss sensitivity.

The key design idea is that **utility is representation-dependent**. A feature that is highly valuable at item level may be almost useless once aggregated.

Design intent:
- Avoid over-protecting features that are already low value.
- Avoid under-protecting features whose signal collapses under noise.
- Make privacy–utility tradeoffs explicit.

---

### Phase 4 — Boundary and Granularity Synthesis

This is the system’s core decision layer.

The Control Plane synthesizes privacy risk, utility intent, and policy constraints into a binding recommendation:

- Which DP boundary must be used?
- At which granularity is this feature allowed to exist?
- Under what fallback or downgrade rules?

This is not an unconstrained optimization. Hard policy constraints (e.g., “never allow item-level under Central DP”) bind first; utility optimization happens within the remaining feasible region.

Design intent:
- Encode trust assumptions explicitly.
- Prevent unsafe representations from ever entering runtime.
- Systematize what is otherwise manual governance.

---

### Phase 5 — Contract Materialization

Finally, the Control Plane compiles all decisions into **machine-enforceable contracts**:

- RFC schemas (what fields are allowed at each interface),
- Transform plans (how to bucketize or map),
- Bounding plans (how to cap sensitivity),
- Granularity plans (k-thresholds and downgrade ladders),
- DP configurations (mechanisms and parameters).

These artifacts are versioned, distributed, and consumed by the runtime plane. Runtime systems do not re-decide privacy; they simply enforce what the Control Plane has declared.

Design intent:
- Eliminate policy drift.
- Make behavior reproducible and auditable.
- Allow privacy changes without rewriting pipelines.

---

## Why This Architecture Matters

The Control Plane turns privacy from an operational afterthought into a **design-time optimization layer**.

It makes three things possible that are not feasible in traditional pipelines:

1. **Adaptive privacy**: different features receive different protections based on structural risk.
2. **Intent-aligned representations**: granularity is chosen for utility, not convenience.
3. **Governance at scale**: policy becomes code, not review tickets.

Most importantly, it enables the system to answer a question that conventional DP pipelines cannot:

> *What is the most informative representation of this feature that is still safe to use under our privacy, fairness, and trust constraints?*

That question is the Control Plane’s entire reason for existing.
---

If you want, next we can write the matching **Runtime Plane** section in the same design-doc style (principles → phases → intent), so the two halves mirror each other conceptually instead of reading like a spec.


- ingests data,
- applies transformations,
- enforces contribution bounds,
- executes Local / Shuffle / Central DP paths,
- produces released tables.

It **never re-decides privacy**.  
It only enforces what the Control Plane has declared.

---




# Design Document: Adaptive Privacy-Aware Data System

## 1. Motivation and Problem Statement

Modern data platforms in fintech, healthcare, and e-commerce rely on user-level behavioral signals to build predictive models. These signals are inherently privacy-sensitive, either directly (e.g., health attributes, financial transactions) or indirectly (e.g., behavioral traces that can be linked or inferred).

The standard approaches used today fall into three categories:

1) **Uniform anonymization**  
   Apply the same de-identification or DP mechanism to all features.

2) **Rule-based sensitivity labeling**  
   Categorize features as “sensitive” vs “non-sensitive” and hard-code handling rules.

3) **Post-hoc DP injection**  
   Add noise at release time without redesigning feature representations.

All three approaches are structurally flawed.

They assume that privacy risk is a property of *fields*.  
In reality, privacy risk is a property of *representations*.

The same underlying signal can be:

- catastrophically unsafe at item level,
- moderately risky at cluster level,
- essentially harmless at aggregate level.

Furthermore, privacy protection mechanisms induce **systematic data degradation**:

- DP noise increases variance,
- clipping introduces bias,
- aggregation collapses heterogeneity,
- opt-out induces missingness bias,
- unlinkability destroys cross-feature joins.

These effects are not uniform across features or granularities.  
Therefore, privacy cannot be treated as a post-processing step.

**Core design objective:**

> Select, for each feature, the representation (granularity + DP boundary) that maximizes predictive utility subject to privacy and fairness constraints.

This is a **structural optimization problem**, not a noise-tuning problem.

---

## 2. Formal Problem Definition

Let:

- \( f \) denote a feature.
- \( g \in \{\text{item}, \text{cluster}, \text{aggregate}\} \) denote representation granularity.
- \( b \in \{\text{local}, \text{shuffle}, \text{central}\} \) denote the privacy boundary.
- \( \mathcal{C}_{\text{policy}} \) denote hard policy constraints (regulatory, governance, trust).

We define three functions:

- \( U(f, g, b) \): expected predictive utility.
- \( R(f, g, b) \): privacy risk.
- \( F(f, g, b) \): fairness risk.

The system solves:

\[
\max_{g, b} \quad U(f, g, b)
\]

subject to:

\[
R(f, g, b) \le \tau_{\text{privacy}}
\]

\[
F(f, g, b) \le \tau_{\text{fairness}}
\]

\[
(g, b) \in \mathcal{C}_{\text{policy}}
\]

This makes explicit that:

- privacy is a *constraint*, not an afterthought,
- granularity and boundary are *decision variables*,
- and utility is representation-dependent.

---

## 3. Why Privacy Is Structurally Important (Not Just Legally)

Privacy matters here for three independent technical reasons.

### 3.1 Linkability is a structural leakage channel

Even without identifiers, high-cardinality, stable, sparse features can be joined with external datasets.

Formally, joinability increases with:

- cardinality of the key space \( K_g \),
- temporal stability \( S(f) \),
- uniqueness \( U(f) \).

No amount of DP noise added *after* linkage can undo a successful join.

Therefore, **representation choice dominates noise magnitude**.

---

### 3.2 Uniqueness is a representation property

Let:

- \( n_c \) = contributor count in cell \( c \).

Then k-anonymity violations occur when:

\[
\mathbb{P}(n_c < k) \text{ is non-negligible}.
\]

Item-level representations massively amplify this probability.  
Cluster-level representations reduce it.  
Aggregate-level representations collapse it.

This cannot be fixed by adding noise alone.

---

### 3.3 Inferability grows with representational richness

Let \( A \) be a sensitive attribute.

If a model \( h(f) \) can predict \( A \) from feature \( f \) with high AUC:

\[
I(f) = \text{AUC}(h(f), A)
\]

then releasing \( f \) increases privacy risk even if it is anonymized.

Again: noise magnitude does not remove structural predictability.

---

## 4. Privacy Risk Model: Local Privacy Score (LPS)

Privacy risk is modeled as a vector:

\[
\text{LPS}(f, g, b) =
\left[
L(f, g, b),\;
U(f, g, b),\;
I(f, g, b),\;
P(f, g, b)
\right]
\]

### 4.1 Linkability Risk \( L \)

Let:

- \( K_g \) = cardinality at granularity \( g \)
- \( J(f) \) = empirical join success rate
- \( S(f) \) = temporal stability
- \( A(b) \) = anonymization strength (Local > Shuffle > Central)

\[
L(f, g, b)
=
\alpha_1 \log K_g
+
\alpha_2 J(f)
+
\alpha_3 S(f)
-
\alpha_4 A(b)
\]

---

### 4.2 Uniqueness Risk \( U \)

Let:

- \( n_c \) = contributors per cell
- \( H_g \) = entropy at granularity \( g \)

\[
U(f, g, b)
=
\mathbb{E}_c [\mathbb{1}(n_c < k)]
+
\beta_1 / H_g
\]

---

### 4.3 Inferability Risk \( I \)

Let:

- \( A \) be a sensitive attribute
- \( h(f) \) be a probing model

\[
I(f, g, b) = \text{AUC}(h(f), A)
\]

---

### 4.4 Policy Exposure \( P \)

\[
P(f, g, b)
=
\sum_{r \in \mathcal{R}}
\lambda_r \cdot \mathbb{1}[(f, g, b) \text{ violates rule } r]
\]

---

## 5. Utility Model Under Privacy-Induced Degradation

Utility is modeled as:

\[
U(f, g, b)
=
\frac{H(f, g)}{\sigma^2(f, g, b) + \text{Bias}(f, g, b) + \epsilon}
\]

where:

- \( H(f, g) \): heterogeneity retained at granularity \( g \)
- \( \sigma^2(f, g, b) \): effective DP noise variance
- \( \text{Bias}(f, g, b) \): clipping + missingness bias

### 5.1 DP Noise Variance

For count queries:

- Central DP:
  \[
  \sigma^2 \approx \frac{2 \log(1.25/\delta)}{\varepsilon^2}
  \]

- Local DP:
  \[
  \sigma^2 \propto \frac{1}{n (e^\varepsilon - 1)^2}
  \]

- Shuffle DP:
  \[
  \sigma^2 \approx \frac{1}{n} \cdot \text{polylog}(n)
  \]

---

### 5.2 Aggregation Effect on Heterogeneity

Let:

- \( H(f, \text{item}) = 1 \)
- \( H(f, \text{cluster}) = \rho < 1 \)
- \( H(f, \text{aggregate}) = 0 \)

This formalizes that aggregation collapses modeling signal.

---

## 6. Boundary and Granularity Optimization

Define feasible set:

\[
\mathcal{F}(f)
=
\{ (g, b) \mid \text{LPS}(f, g, b) \le \boldsymbol{\tau} \}
\]

Optimal representation:
$$ [(g^*, b^*)=\arg\max_{(g, b) \in \mathcal{F}(f)} U(f, g, b)] $$
$$ \[(g^*, b^*)=\arg\max_{(g, b) \in \mathcal{F}(f)} U(f, g, b)\] $$

---

## 7. Granularity Downgrade Ladder

If \( (g, b) \notin \mathcal{F}(f) \):

\[
\text{item} \rightarrow \text{cluster} \rightarrow \text{aggregate}
\]

Stop at first feasible \( g \).

---

## 8. Runtime Enforcement

The Control Plane emits:

- RFC schemas
- TransformPlan
- BoundingPlan
- GranularityPlan
- DPConfig

The runtime plane enforces these deterministically.

---

## 9. Innovations

1) Privacy as structural optimization  
2) Granularity as a first-class variable  
3) Boundary selection as a trust decision  
4) Representation-aware privacy modeling  
5) Automated downgrade instead of suppression

---

## 10. Summary

This system replaces uniform anonymization with adaptive representation selection under formal privacy constraints. It treats privacy as a design-time optimization variable, not a post-hoc filter.

---



