"""
Structured knowledge base for model auditability.

Each topic is a dict with:
  id        — unique slug
  title     — short display title
  keywords  — list of words/phrases that trigger this topic (all lowercase)
  body      — human-readable explanation (plain text, terminal-friendly)
  equations — optional list of key equations as plain-text strings
  references — optional list of full citations
  source_files — implementation locations in the codebase
"""
from __future__ import annotations

TOPICS: list[dict] = [

    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "overview",
        "title": "Architecture Overview",
        "keywords": [
            "overview", "architecture", "how does it work", "pipeline",
            "workflow", "how is the design", "how are calculations done",
            "what models", "what calculations", "what is implemented",
            "general", "high level", "summary",
        ],
        "body": """\
ARCHITECTURE OVERVIEW
─────────────────────
nucsys-agent runs a deterministic five-stage multi-physics sizing pipeline to
turn a natural-language query into a sized nuclear plant topology.

**1 — SPEC PARSING**
A natural-language query is parsed into a `DesignSpec` (system type, thermal
power, coolant, pressures, temperatures). Regex rules cover common patterns;
an LLM (Anthropic or OpenAI) is invoked when available for ambiguous input.

**2 — TOPOLOGY SELECTION**
A `CardStore` is searched for the best-matching `PatternCard`. Each card
defines node types (reactor core, steam generator, pump, turbine, valve) and
their connectivity as a directed graph. The highest-scoring card for the
requested system type is selected and instantiated as a set of `Building`
objects.

**3 — PRIMARY ΔT OPTIMISATION**
A 21-point grid from 20 K to 60 K is swept. For each candidate ΔT the full
thermal and hydraulic model is run and a score computed:

`score = w_pump · P_pump + w_UA · UA`

The ΔT that minimises this score (subject to a ≥ 10 K pinch margin) is
selected. Default weights balance a 1 MW change in pump power against a
5 000 W/K change in SG UA.

**4 — COMPONENT SIZING**
Using the optimal ΔT, all nodes are sized in a single pass:
- **Primary loop** — mass flow from Q = ṁ · cp · ΔT; coolant properties from IAPWS97 / Sobolev / PR-EOS
- **Steam generator** — UA from counter-flow LMTD; heat-transfer area from a thermal-resistance network (film coefficients + fouling + tube wall)
- **Primary pump** — shaft power from Darcy-Weisbach with the Churchill (1977) explicit friction factor
- **Rankine BOP** — 4-state cycle via IAPWS97 (polynomial fallback if not installed); turbine exit quality checked against 0.87 moisture limit
- **Feedwater pump** — incompressible pump work from Rankine State 3 → 4

**5 — VALIDATION & EXPORT**
Node and edge integrity is checked against a component ontology allowlist.
The design is serialised as an Alchemy-format JSON graph (buildings → parts
→ edges) and validated against a published JSON Schema.
""",
        "references": [],
        "source_files": [
            "nucsys_agent/workflow.py   — orchestrates all five stages",
            "nucsys_agent/optimizer.py  — stage 3 ΔT grid search",
            "nucsys_agent/rag/store.py  — stage 2 card retrieval",
            "nucsys_agent/sizing/       — stage 4 thermal/hydraulic models",
        ],
    },

    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "energy_conservation",
        "title": "Energy Conservation",
        "keywords": [
            "energy conservation", "energy balance", "first law",
            "conservation of energy", "heat balance", "thermal balance",
            "how is energy", "q = m", "q=m", "mass flow", "enthalpy balance",
            "power balance", "energy equation", "steady state",
        ],
        "body": """\
ENERGY CONSERVATION
───────────────────
All thermal calculations assume steady-state operation with no heat losses
(Q_primary → SG → secondary side with 100 % thermal effectiveness at the
loop level — losses are accounted for at the plant-level design stage).

PRIMARY LOOP  (Q = ṁ · cp · ΔT)
  The primary mass flow rate is derived directly from the energy balance:

    ṁ = Q_th / (cp · ΔT_primary)

  where:
    Q_th       — reactor thermal power [W]
    cp         — specific heat evaluated at bulk primary temperature
                 T_bulk = T_hot − 0.5 · ΔT_primary   [J/(kg·K)]
    ΔT_primary — hot-leg to cold-leg temperature rise [K]

  cp (and ρ, μ, k) come from the coolant-specific correlations described
  in the "fluid properties" topic.

STEAM GENERATOR ENERGY BALANCE
  SG duty equals the full primary thermal power:
    Q_SG = Q_th

  The LMTD and UA product follow from the temperature boundary conditions:
    LMTD = (ΔT₁ − ΔT₂) / ln(ΔT₁/ΔT₂)        (counter-flow)
    UA   = Q_SG / LMTD                         [W/K]
    A    = UA / U                               [m²]

RANKINE CYCLE ENERGY BALANCE (secondary side)
  The cycle is closed by four enthalpy states (IAPWS97):
    State 1: turbine inlet  (P_boiler, T_steam)  → h₁, s₁
    State 2: turbine exit   (P_cond,   actual)    → h₂ = h₁ − η_is·(h₁−h₂ₛ)
    State 3: condenser exit (P_cond,   sat liquid) → h₃
    State 4: pump exit      (P_boiler, compressed) → h₄ = h₃ + v₃·ΔP/η_pump

  Heat added in SG:   q_in  = h₁ − h₄           [kJ/kg]  (pump exit as SG inlet)
  Turbine work:       w_t   = h₁ − h₂            [kJ/kg]
  Pump work:          w_p   = v₃ · ΔP / η_pump   [kJ/kg]  (incompressible approx.)
  Condenser heat:     q_c   = h₂ − h₃            [kJ/kg]
  First-law check:    q_in  = w_t − w_p + q_c    ✓ (satisfied exactly)

  Secondary mass flow: ṁ_sec = Q_th / q_in        [kg/s]

  Note: h_fw (T_feedwater_C at SG inlet) is stored for display / SG UA sizing.
  For efficiency, the simple cycle uses h₄ — this gives ~31–35 % for PWR
  secondary conditions (not the ~43 % from using h_fw at 220 °C, which would
  require modelling steam extraction for feedwater heating).

MOISTURE WARNING
  Turbine exit quality x₂ is computed and stored.  The design is flagged
  if x₂ < 0.87 (excessive last-stage moisture; reheat or higher T_steam advised).
""",
        "equations": [
            "ṁ = Q_th / (cp · ΔT)",
            "UA = Q_SG / LMTD",
            "w_turb = h₁ − h₂  (actual, after isentropic efficiency)",
            "w_pump ≈ v₃ · ΔP / η_pump",
            "η_net = W_net / Q_th",
        ],
        "references": [
            "Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., Chapter 11 (heat exchangers)",
            "IAPWS-IF97, Release on the IAPWS Industrial Formulation 1997 for the Thermodynamic Properties of Water and Steam",
        ],
        "source_files": ["nucsys_agent/sizing/thermo.py", "nucsys_agent/sizing/rankine.py"],
    },

    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "fluid_properties",
        "title": "Fluid Thermophysical Properties",
        "keywords": [
            "fluid properties", "thermophysical", "coolant properties",
            "properties implemented", "fluid models", "where do properties come from",
            "sodium properties", "water properties", "co2 properties",
            "helium properties", "iapws", "peng robinson", "sobolev",
            "nist", "specific heat", "density", "viscosity", "conductivity",
            "prandtl", "cp model", "eos", "equation of state",
            "correlations", "what correlations", "fluid correlations",
            "sodium", "helium", "co2", "coolant model",
        ],
        "body": """\
FLUID THERMOPHYSICAL PROPERTIES
────────────────────────────────
Four coolants are supported, each using a different correlation source.

WATER  (compressed liquid, ~250–350 °C, 10–18 MPa)
  Primary path : IAPWS-IF97 via the `iapws` Python package (optional install).
                 Full property set: ρ, cp, h, s, μ, k.
                 Accuracy: ρ < 0.1 %, cp < 0.2 % in the sub-critical liquid region.
  Fallback path: Polynomial fits calibrated vs NIST steam-table data at 15.5 MPa.
                 Valid range: 250–340 °C.
                 Accuracy: ρ ± 1 %, cp ± 2 %, μ ± 5 %, k ± 2 %.
  Reference: Rogers & Mayhew, Engineering Thermodynamics, 4th ed.;
             NIST WebBook, water properties at 15.5 MPa.

SODIUM  (liquid, 98–850 °C)
  Source : Sobolev (2011), SCK·CEN-BLG-1069.
           All correlations use T in Kelvin.
  Equations:
    ρ  = 1011.02 − 0.22046 · T_K                          [kg/m³]
    cp = 1652.5  − 0.8380 · T_K + 4.6535×10⁻⁴ · T_K²    [J/(kg·K)]
    k  = 104.0   − 0.047 · T_K + 1.16×10⁻⁵ · T_K²       [W/(m·K)]
    μ  = 4.56×10⁻⁴ · exp(616.6 / T_K)                    [Pa·s]
  Valid range: 371 K (98 °C, melting point) to ~893 K (620 °C).

CO₂  (supercritical / compressed gas, T > 50 °C, P > 7.5 MPa)
  Density   : Peng-Robinson EOS (Peng & Robinson, 1976).
              Cubic Z-equation solved via numpy.roots; ideal-gas fallback
              if no physical root found.
              Critical constants: Tc = 304.13 K, Pc = 7.38 MPa, ω = 0.2239.
  Ideal cp  : NIST Shomate equation (Chase, 1998), valid 298–1200 K.
              Departure from ideal-gas cp < 8 % at T > 150 °C, P > 10 MPa.
  Transport : Power-law fits calibrated against NIST WebBook at 10–30 MPa:
                μ = 1.38×10⁻⁵ · (T_K/300)⁰·⁷⁰  [Pa·s]
                k = 0.032     · (T_K/300)⁰·⁷²  [W/(m·K)]
  Best path : CoolProp library (optional) — used automatically if installed,
              overriding all of the above with reference-quality data.
  ⚠  Do NOT use near the critical point (T ≈ 31 °C, P ≈ 7.4 MPa) where
     the Peng-Robinson EOS and ideal-cp approximation both break down.

HELIUM  (ideal gas, T = 200–900 °C, P = 3–9 MPa)
  Density  : Ideal-gas law  ρ = P / (R_He · T_K),  R_He = 2077.1 J/(kg·K)
  cp       : Constant 5193 J/(kg·K)  (monoatomic ideal gas, γ = 5/3)
  Transport: Power-law fits calibrated vs NIST WebBook, 300–1200 K, error < 3 %:
               μ = 2.00×10⁻⁵ · (T_K/300)⁰·⁶⁷  [Pa·s]
               k = 0.1513    · (T_K/300)⁰·⁶⁷  [W/(m·K)]
  Reference: Incropera et al., Table A.4;  NIST WebBook, Helium.

PROPERTY DISPATCH
  All models are accessed through a single function:
    get_liquid_props(coolant, P_MPa, T_C) → ThermoProps
  which returns a dataclass with cp, ρ, μ, k, h, s, Pr as available.
""",
        "references": [
            "IAPWS, Release on the IAPWS Industrial Formulation 1997 (IF97)",
            "Sobolev, V. (2011). Database of thermophysical properties of liquid metal coolants for GEN-IV. SCK·CEN-BLG-1069",
            "Peng, D.Y. & Robinson, D.B. (1976). A new two-constant equation of state. Ind. Eng. Chem. Fundam., 15(1), 59–64",
            "Chase, M.W. Jr. (1998). NIST-JANAF Thermochemical Tables, 4th ed. (CO₂ Shomate coefficients)",
            "Incropera, F.P. et al. (2007). Fundamentals of Heat and Mass Transfer, 7th ed. Table A.4 (Helium)",
        ],
        "source_files": ["nucsys_agent/sizing/properties.py"],
    },

    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "heat_exchanger",
        "title": "Steam Generator / Heat Exchanger Sizing",
        "keywords": [
            "heat exchanger", "steam generator", "sg sizing", "sg model",
            "lmtd", "ua product", "u value", "overall heat transfer",
            "fouling", "thermal resistance", "tube wall", "inconel",
            "heat transfer coefficient", "film coefficient", "nusselt",
            "dittus boelter", "gnielinski", "seban shimazaki",
            "area calculation", "hx area", "counter flow",
        ],
        "body": """\
STEAM GENERATOR / HEAT EXCHANGER SIZING
─────────────────────────────────────────
The SG is modelled as a counter-flow shell-and-tube heat exchanger.

STEP 1 — LMTD (counter-flow)
  ΔT₁ = T_primary,hot,in  − T_secondary,hot,out
  ΔT₂ = T_primary,hot,out − T_secondary,cold,in
  LMTD = (ΔT₁ − ΔT₂) / ln(ΔT₁ / ΔT₂)

  An F-correction factor is available for multi-pass arrangements (default F=1.0,
  pure counter-flow — appropriate for U-tube and helical-coil nuclear SGs).

STEP 2 — UA product
  UA = Q_SG / LMTD     [W/K]

STEP 3 — Overall heat-transfer coefficient U  (thermal resistance network)
  1/U = 1/h_primary + R_f,primary + t_wall/k_wall + R_f,secondary + 1/h_secondary

  Film coefficients h are conservative fixed values derived from standard
  correlations at typical nuclear operating conditions:

    Water  primary (PWR, Re ~ 5×10⁵):  h = 30 000 W/(m²·K)
      basis: Dittus-Boelter, turbulent flow in tube bundle, mid-range estimate
    Sodium primary (SFR, liquid metal): h = 80 000 W/(m²·K)
      basis: Seban-Shimazaki  Nu = 5.0 + 0.025·Pe^0.8
    CO₂ primary (sCO₂, 20 MPa):        h =  4 000 W/(m²·K)
      basis: Gnielinski correlation, mid-range estimate
    Helium primary (HTGR, 7 MPa):      h =    800 W/(m²·K)
      basis: Dittus-Boelter, low-ρ gas, conservative
    Secondary (steam/boiling):         h = 15 000 W/(m²·K)
      basis: conservative nucleate/convective boiling

  Fouling resistances (TEMA nuclear-grade, tightly controlled chemistry):
    Water primary:  R_f = 2.0×10⁻⁵ m²·K/W  (TEMA R2)
    Sodium:         R_f = 5.0×10⁻⁶ m²·K/W  (liquid metal, very clean)
    CO₂ / He:       R_f = 1.0×10⁻⁵ m²·K/W
    Secondary side: R_f = 1.0×10⁻⁵ m²·K/W

  Tube wall geometry (defaults):
    t_wall = 2.0 mm  (typical HX tube)
    k_wall = 16 W/(m·K)  (SS-316 / Inconel-600 mid-range)
    Thin-wall approximation: A_inner ≈ A_outer  (valid for t/D < 0.1)

STEP 4 — Heat-transfer area
  A = UA / U     [m²]

  The area is a lower bound — it corresponds to new, clean tubing.  A design
  margin (typically 10–20 %) should be added in detailed design.
""",
        "equations": [
            "LMTD = (ΔT₁ − ΔT₂) / ln(ΔT₁/ΔT₂)  [counter-flow]",
            "UA = Q / LMTD",
            "1/U = 1/h_p + R_f,p + t/k_wall + R_f,s + 1/h_s",
            "A = UA / U",
        ],
        "references": [
            "Incropera et al., Fundamentals of Heat and Mass Transfer, 7th ed., Chapter 11",
            "Bowman, Mueller & Nagle (1940). Mean temperature difference in design. Trans. ASME 62, 283 (LMTD F-correction charts)",
            "Seban & Shimazaki (1951). Heat transfer to a fluid flowing turbulently in a smooth pipe with walls at constant temperature. Trans. ASME, 73, 803 (sodium Nu correlation)",
            "TEMA Standards, 9th ed. (fouling resistance tables)",
        ],
        "source_files": ["nucsys_agent/sizing/thermo.py"],
    },

    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "rankine_cycle",
        "title": "Rankine Cycle (Balance of Plant)",
        "keywords": [
            "rankine", "rankine cycle", "turbine", "turbine power",
            "turbine efficiency", "isentropic", "cycle efficiency",
            "net power", "gross power", "condenser", "feedwater",
            "pump work", "steam quality", "moisture", "bop",
            "balance of plant", "iapws", "steam enthalpy",
            "turbine exit", "wet steam",
        ],
        "body": """\
RANKINE CYCLE  (Balance of Plant)
───────────────────────────────────
A simple, non-regenerative Rankine cycle with one turbine stage and a
condenser.  The cycle is closed through four states.

CYCLE STATES  (IAPWS-IF97 primary; polynomial fallback if `iapws` not installed)
  State 1 — Turbine inlet      : P_boiler, T_steam  →  h₁, s₁
  State 2s — Isentropic exit   : P_cond, s=s₁       →  h₂ₛ
  State 2  — Actual exit       : h₂ = h₁ − η_is·(h₁ − h₂ₛ)
  State 3  — Condenser exit    : P_cond, x=0 (sat. liquid)  →  h₃, v₃
  State 4  — Pump exit         : h₄ = h₃ + v₃·(P_boiler − P_cond)×1000/η_pump
  FW state — SG inlet (display) : P_boiler, T_feedwater  →  h_fw  (informational only)

POWER AND EFFICIENCY
  Secondary mass flow: ṁ = Q_in·10³ / (h₁ − h₄)       [kg/s]  (simple cycle)
  Turbine gross:       W_gross = ṁ·(h₁ − h₂) / 10³     [MW_e]
  Pump work:           W_pump  = ṁ·(h₄ − h₃) / 10³     [MW_e]
  Net output:          W_net   = W_gross − W_pump        [MW_e]
  Cycle efficiency:    η_cycle = W_net / Q_in            [−]

DEFAULT EFFICIENCIES
  Turbine isentropic:   η_is   = 0.87  (typical for LP/HP nuclear turbine)
  Feedwater pump:       η_pump = 0.80

MOISTURE FRACTION
  Turbine exit quality x₂ is computed from (h₂, P_cond) via IAPWS97.
  x₂ < 0.87 → warning: excessive moisture in last turbine stage.
  Mitigation: raise steam temperature, add moisture separator, or reheat.

FALLBACK MODEL  (polynomial, used when `iapws` is not installed)
  Steam enthalpy from simplified Antoine-style fits to NIST steam tables:
    h_g_sat(T_sat) ≈ 2675 + 1.82·(T_sat−100) − 2.3×10⁻³·(T_sat−100)²  [kJ/kg]
    T_sat(P_MPa)   ≈ 168.8 + 22.4·ln(P) + 0.85·ln(P)²                  [°C]
  Accuracy vs IAPWS97: ~3–5 % on efficiency and mass flow.
""",
        "equations": [
            "h₂ = h₁ − η_is · (h₁ − h₂ₛ)  (actual turbine exit enthalpy)",
            "ṁ_sec = Q_in·10³ / (h₁ − h₄)  (secondary mass flow, simple cycle)",
            "W_net = ṁ·(h₁−h₂)/10³ − ṁ·v₃·ΔP/η_pump  [MW_e]",
            "η_cycle = W_net / Q_in",
        ],
        "references": [
            "IAPWS, Release on the IAPWS Industrial Formulation 1997 for the Thermodynamic Properties of Water and Steam (IF97)",
            "Çengel & Boles, Thermodynamics: An Engineering Approach, 9th ed., Chapter 10 (Rankine cycle)",
        ],
        "source_files": ["nucsys_agent/sizing/rankine.py"],
    },

    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "hydraulics",
        "title": "Pump Sizing and Hydraulics",
        "keywords": [
            "pump", "pump sizing", "hydraulics", "pressure drop",
            "friction factor", "churchill", "darcy", "darcy weisbach",
            "moody", "reynolds", "pipe", "roughness", "minor loss",
            "pumping power", "primary pump", "feedwater pump",
            "reactor vessel", "core pressure drop", "pipe diameter",
            "velocity", "loop geometry",
        ],
        "body": """\
PUMP SIZING AND HYDRAULICS
────────────────────────────
The primary coolant pump is sized using a physics-based Darcy-Weisbach model.

FRICTION FACTOR — Churchill (1977) explicit formula
  Valid for all flow regimes (laminar, transition, turbulent) and all ε/D.
  Maximum error vs Moody chart: < 1 %.

  Let  ε/D = roughness / diameter
       A   = (−2.457 · ln((7/Re)⁰·⁹ + 0.27·ε/D))¹⁶
       B   = (37530/Re)¹⁶
       f   = 8 · ((8/Re)¹² + (A+B)⁻¹·⁵)^(1/12)

  Reference: Churchill, S. W. (1977). Chemical Engineering, 84(24), 91–92.

PRESSURE DROP DECOMPOSITION
  Total primary-loop ΔP is split into three terms:
    ΔP_pipe   = f · (L/D) · (½ρV²)    — straight piping (Darcy-Weisbach)
    ΔP_minor  = K_fittings · (½ρV²)   — bends, valves, reducers
    ΔP_vessel = K_vessel · (½ρV²)     — reactor vessel / core (lumped form loss)
    ΔP_total  = ΔP_pipe + ΔP_minor + ΔP_vessel

AUTO PIPE SIZING
  When no pipe diameter is specified, the pipe is sized for a coolant-appropriate
  target bulk velocity (standard engineering practice):
    D = sqrt(4 · ṁ / (π · ρ · V_target))

  Target velocities:
    Water  (PWR)  : 5 m/s   — typical for 0.7–0.9 m ID PWR cold/hot leg
    Sodium (SFR)  : 4 m/s
    CO₂   (sCO₂) : 8 m/s   — higher velocity for low-ρ gas
    Helium (HTGR) : 12 m/s

LOOP GEOMETRY DEFAULTS  (per-coolant, based on plant literature)
  Water (PWR):   D = 0.762 m, L = 50 m, K_fittings = 10, K_vessel = 3.5
    Basis: 30-in schedule pipe; L covers hot leg + cold leg + crossover
           per loop; K_vessel from PWR core flow tests (Todreas & Kazimi)
  Sodium (SFR):  D = 0.450 m, L = 30 m, K_fittings = 8,  K_vessel = 3.8
    Basis: wire-wrapped fuel pin bundle has higher form drag than PWR
  CO₂ (sCO₂):   D = 0.350 m, L = 20 m, K_fittings = 6,  K_vessel = 25.0
    Basis: prismatic core + IHX layout; target core ΔP ≈ 0.1 MPa at 20 MPa
  Helium (HTGR): D = 0.300 m, L = 20 m, K_fittings = 6,  K_vessel = 200
    Basis: pebble-bed core (Ergun-dominated ΔP); PBMR-400 data gives
           core ΔP ≈ 0.035–0.05 MPa (circulator power ≈ 2–3 % of Q_th)

SHAFT POWER
  P_shaft = (ṁ / ρ) · ΔP / η_pump     [W]

FEEDWATER PUMP  (Rankine cycle)
  Sized from the incompressible approximation already embedded in the Rankine
  closure (State 3→4 in rankine.py); not re-computed separately.
""",
        "equations": [
            "f (Churchill) = 8·((8/Re)¹² + (A+B)⁻¹·⁵)^(1/12)",
            "ΔP = (f·L/D + K)·½ρV²  [Pa]",
            "P_shaft = (ṁ/ρ)·ΔP/η  [W]",
        ],
        "references": [
            "Churchill, S.W. (1977). Friction-factor equation spans all fluid-flow regimes. Chemical Engineering, 84(24), 91–92",
            "Todreas, N.E. & Kazimi, M.S. (2012). Nuclear Systems Vol. 1, 2nd ed. (PWR hydraulic data, Chapter 3)",
            "IAEA-TECDOC-1348 (2003). Thermal-hydraulic data for sodium-cooled reactors",
        ],
        "source_files": ["nucsys_agent/sizing/hydraulics.py"],
    },

    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "optimizer",
        "title": "Optimizer — Primary ΔT Grid Search",
        "keywords": [
            "optimizer", "optimiser", "optimization", "optimisation",
            "how does the optimizer", "how does the optimiser",
            "how optimizer works", "optimizer work",
            "objective function", "objective", "grid search", "sweep",
            "primary delta t", "primary deltaT", "score", "minimize",
            "minimise", "trade off", "tradeoff", "pump vs ua",
            "w_pump", "w_ua", "weights", "pinch", "constraint",
        ],
        "body": """\
OPTIMIZER — PRIMARY ΔT GRID SEARCH
────────────────────────────────────
The optimizer selects the primary temperature difference ΔT that best balances
pumping power against heat-exchanger size (UA product).

ALGORITHM
  Brute-force sweep over a uniform grid of ΔT values (default: 21 points
  from 20 K to 60 K).  For each candidate ΔT:

    1. Compute primary mass flow: ṁ = Q / (cp · ΔT)
    2. Size the primary pump via the Darcy-Weisbach model  → P_pump [MW]
    3. Compute counter-flow LMTD from the four temperature boundary conditions
    4. Compute UA = Q / LMTD  [W/K]
    5. Evaluate the objective score:
         score = w_pump · P_pump + w_UA · UA
    6. Reject candidates that violate the pinch constraint:
         T_primary,cold − T_secondary,hot,out ≥ min_pinch  (default 10 K)

  The ΔT with the lowest score is selected.

OBJECTIVE FUNCTION WEIGHTS
  w_pump = 1.0    (MW)
  w_UA   = 2×10⁻⁴  (MW/K → MW by dimensional normalisation)

  These weights were chosen so that a 1 MW change in pumping power is
  equivalent to a change of 5 000 W/K in UA.  In practice, the balance means:
    • Higher ΔT → smaller ṁ → smaller pump → lower P_pump
    •           → larger LMTD → smaller UA required → smaller SG
    • Lower ΔT  → opposite trade-off

  The weights can be changed in AgentConfig (config.py).

OPTIMIZATION OBJECTIVE
  The "balanced" objective (default) minimises the combined score above.
  Named presets:
    "balanced"          → w_pump = 1.0, w_UA = 2×10⁻⁴
    "min_pump_power"    → w_pump = 1.0, w_UA = 1×10⁻⁶  (almost ignore UA)
    "min_UA"            → w_pump = 1×10⁻³, w_UA = 2×10⁻⁴  (almost ignore pump)

NOTE ON SCOPE
  Only the primary ΔT is optimised.  Secondary-side conditions (steam pressure,
  condenser pressure, feedwater temperature) are fixed design inputs.
  A full multi-variable optimisation is outside the scope of preliminary sizing.
""",
        "equations": [
            "score = w_pump · P_pump + w_UA · UA",
            "subject to: T_primary,cold − T_secondary,hot ≥ 10 K  (pinch constraint)",
        ],
        "references": [
            "Nocedal & Wright, Numerical Optimization, 2nd ed. (grid search context)",
        ],
        "source_files": ["nucsys_agent/optimizer.py", "nucsys_agent/config.py"],
    },

    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "assumptions",
        "title": "Model Assumptions and Limitations",
        "keywords": [
            "assumptions", "limitations", "simplifications", "what is assumed",
            "model assumptions", "what are the assumptions", "what assumptions",
            "assumptions made", "model limits", "scope", "validity",
            "not modelled", "steady state", "single phase", "single loop",
            "what is not included", "what is not modelled", "caveats", "warning",
            "accurate", "accuracy", "how accurate", "model accuracy", "error",
            "valid range", "validity range",
        ],
        "body": """\
MODEL ASSUMPTIONS AND LIMITATIONS
───────────────────────────────────
These are the principal assumptions embedded in the sizing models.
Users should verify each assumption is appropriate for their application.

GENERAL
  ✓ Steady-state, full-power operation only.  No transient analysis.
  ✓ No heat losses from primary loop piping (conservative for UA; optimistic for pump).
  ✓ Single-loop equivalent model.  For multi-loop plants, the result represents
    one equivalent loop; actual loop count is not modelled.
  ✓ Uniform coolant properties at bulk average temperature.

PRIMARY LOOP / STEAM GENERATOR
  ✓ Counter-flow LMTD (F = 1.0).  Valid for U-tube and helical-coil SGs.
    Not valid for multi-pass cross-flow arrangements without F-correction.
  ✓ Fixed film coefficients (see heat exchanger topic).  These are conservative
    mid-range estimates; actual values depend on Re, geometry, and Nu correlation.
  ✓ Thin-wall tube approximation for U calculation.  Valid when t_wall/D < 0.1.
  ✓ SG area is a clean-condition lower bound.  A design margin (10–20 %) should
    be added in detailed design to account for fouling growth and plugging.

RANKINE CYCLE
  ✓ Simple (non-regenerative) Rankine cycle — no feedwater heaters or reheating.
    Real nuclear plants use 4–7 feedwater heaters; this raises actual η by 3–8 %.
  ✓ Turbine modelled as a single isentropic stage.  Multi-stage LP/HP separation
    is not represented.
  ✓ Pump work modelled as incompressible (v = v_sat,liq at condenser pressure).
    Error < 0.5 % for typical nuclear BOP conditions.

HYDRAULICS
  ✓ Loop geometry parameters (pipe diameter, length, fittings, vessel K) are
    plant-class averages from published data.  Project-specific geometry will
    differ; override parameters are available.
  ✓ Reactor vessel/core modelled as a single lumped K_vessel coefficient.
    This is appropriate for preliminary sizing only.
  ✓ Single-phase flow throughout.  No two-phase pressure drop in the primary.
  ✓ Gravity (hydrostatic head) is not included.  For natural-circulation reactors
    this is a significant omission.

FLUID PROPERTIES
  ✓ Water: IAPWS97 is highly accurate but the polynomial fallback has ± 1–5 % error.
  ✓ CO₂: Peng-Robinson EOS has ± 2–5 % error for ρ away from the critical point.
    AVOID use near T_c = 31 °C, P_c = 7.4 MPa (properties diverge).
  ✓ Helium and sodium: power-law / linear fits have ± 3–5 % error across the
    valid temperature range; outside the stated range extrapolation is unreliable.

REQUIREMENTS BASELINE
  ✓ 1 500 requirements across 6 component types are derived from generic nuclear
    industry practice.  They are NOT a substitute for a project-specific design
    basis or regulatory compliance analysis.
""",
        "references": [],
        "source_files": [
            "nucsys_agent/sizing/",
            "nucsys_agent/optimizer.py",
        ],
    },

    # ──────────────────────────────────────────────────────────────────────────
    {
        "id": "references",
        "title": "All References",
        "keywords": [
            "references", "citations", "bibliography", "sources",
            "papers", "books", "where does it come from",
            "what references", "references used", "which references",
            "all references", "full references", "reference list",
            "literature", "published", "what literature",
        ],
        "body": """\
ALL REFERENCES
──────────────
Thermodynamics
  [1] IAPWS, Release on the IAPWS Industrial Formulation 1997 for the Thermodynamic
      Properties of Water and Steam (IF97).  www.iapws.org
  [2] Çengel, Y.A. & Boles, M.A. (2018). Thermodynamics: An Engineering Approach,
      9th ed. McGraw-Hill.  (Rankine cycle, Chapter 10)

Heat Transfer
  [3] Incropera, F.P., Dewitt, D.P., Bergman, T.L. & Lavine, A.S. (2007).
      Fundamentals of Heat and Mass Transfer, 7th ed. Wiley.
      (LMTD, NTU-ε, forced convection correlations)
  [4] Bowman, R.A., Mueller, A.C. & Nagle, W.M. (1940). Mean temperature difference
      in design. Trans. ASME, 62, 283–294.  (LMTD F-correction charts)
  [5] Seban, R.A. & Shimazaki, T.T. (1951). Heat transfer to a fluid flowing
      turbulently in a smooth pipe with walls at constant temperature.
      Trans. ASME, 73, 803–807.  (sodium Nu correlation)

Sodium Properties
  [6] Sobolev, V. (2011). Database of thermophysical properties of liquid metal
      coolants for GEN-IV. SCK·CEN-BLG-1069.  (ρ, cp, k, μ correlations for Na)

CO₂ Properties
  [7] Peng, D.Y. & Robinson, D.B. (1976). A new two-constant equation of state.
      Ind. Eng. Chem. Fundam., 15(1), 59–64.  (PR EOS for CO₂ density)
  [8] Chase, M.W. Jr. (1998). NIST-JANAF Thermochemical Tables, 4th ed.
      J. Phys. Chem. Ref. Data, Monograph 9.  (CO₂ Shomate cp coefficients)

Helium / Water Properties (fallback)
  [9] Rogers, G.F.C. & Mayhew, Y.R. (1992). Engineering Thermodynamics, Work and
      Heat Transfer, 4th ed. Pearson.  (compressed water polynomial data)
 [10] NIST WebBook, National Institute of Standards and Technology.
      https://webbook.nist.gov  (He, CO₂, H₂O data)

Hydraulics
 [11] Churchill, S.W. (1977). Friction-factor equation spans all fluid-flow regimes.
      Chemical Engineering, 84(24), 91–92.  (explicit f correlation)
 [12] Todreas, N.E. & Kazimi, M.S. (2012). Nuclear Systems Vol. I: Thermal-Hydraulic
      Fundamentals, 2nd ed. CRC Press.  (PWR hydraulic data, coolant properties)

Loop Geometry
 [13] IAEA-TECDOC-1348 (2003). Thermal hydraulic data for sodium fast reactors.
      International Atomic Energy Agency.
 [14] PBMR (Pty) Ltd. (2006). PBMR-400 Safety Analysis Report, Chapter 3.
      (helium circulator pressure drop data)
""",
        "references": [],
        "source_files": [],
    },
]
