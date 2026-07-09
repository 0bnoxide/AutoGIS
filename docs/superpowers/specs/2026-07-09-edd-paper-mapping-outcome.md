# EDD Paper-Mapping Outcome - verification record (Step 1 of 3)

**Date:** 2026-07-09  
**Method:** 6-format extraction Workflow + Fable high-effort synthesis (run `wf_90e1d7b9-724`).  
**Companion to:** `2026-07-08-canonical-schema-expansion-design.md` (the Step 1 spec this verifies).  
**Status:** verification complete for 5/6 formats; NYSDEC v5 deferred to Step 3 (see Coverage).

This is the spec's *required pre-implementation paper mapping*: a column-by-column reconciliation of real regulatory/commercial lab formats against the proposed canonical field list, done before any field name is frozen (additive-only migration = one shot per name). It also seeds Step 3's deterministic parser, which consumes the same description/valid-values files.

## Coverage

| Format | In-scope fields | Redacted | Role |
|---|---|---|---|
| wqx | 102 | 6 | Step 2 (first real import) |
| mining | 113 | 7 | Step 3 EQuIS |
| wmrd | 166 | 5 | Step 3 EQuIS |
| epar4 | 393 | 6 | Step 3 EQuIS |
| sxsamp | 33 | 3 | Step 3 (opaque fallback) |
| **nysdec** | *(not extracted - agent stalled on 2.2 MB valid-values workbook)* | - | Step 3 EQuIS |

**NYSDEC v5 gap (accepted):** the extraction agent stalled repeatedly on read-volume. Under the *minimal* Step-1 boundary (below) NYSDEC feeds nothing in Step 2, so it does not gate Step 1. Its spot-check moves to Step 3's spec; in-scope sheets: `Sample_v5`, `TestResultQC_v5`, `Batch_v5`, `FieldResults_v5`, `SoilGas_v5`, `VI_Samples_v5`, `VI_TestResultsQC_v5`, `VI_Batches_v5`, `VI_Building_Inspection_v5`, `VI_Building_Parameters_v5`, `BasicChemistry_v5`. The synthesis judged it a close EQuIS cousin of WMRD/EPA-R4.

## Frozen Step-1 boundary decision (2026-07-09)

The one-shot/irreversible constraint bites on only two things: (1) the `Env_AnalyticalResults` UNIQUE_KEYS composition, and (2) field **names on the existing tables** that Step 2/WQX populates. A nullable column or a **brand-new table** is additive-safe to add in Step 3 with zero rename/rekey risk.

**Decision: MINIMAL Step 1** - freeze only what WQX (Step 2) needs; defer everything with no Step-1/Step-2 producer to Step 3, where real EQuIS data verifies it.

| Decision | Choice | Rationale |
|---|---|---|
| Freeze boundary | **Minimal** | Freeze the AnalyticalResults key + WQX-populated field names now; defer `Env_QCResults`, VI fields, EQuIS-only fields (CASNumber, QuantitationLimit, IsReportable) to Step 3. |
| Qualifier semantics (Q#4) | **Final/interpreted** | `Qualifier` holds the authoritative qualifier; IsEstimated derivation reads it. Add InterpretedQualifier later only if needed. |
| ResultBasis wet/dry (Q#5) | **Fold into MethodDilutionKey** | Data column, NOT a key component. Rare wet+dry pairs dedup via the MethodDilutionKey composite. Key stays 11-wide. |
| sxsamp BS1/BS2 (Q#3) | per-lab `value_map` | Lab-specific QCType code map (Step 3), not a schema decision. |
| Limit units (Q#6) | convert-at-load + QA-warn | No `DetectionLimitUnits` column; deferrable additively. |

## Verdict: amendments required

### Confirmed fields (proposed/existing with >=1 real producer)

| Field | Table | Real producers |
|---|---|---|
| CASNumber | Env_AnalyticalResults | mining:Characteristic_ID (rt_analyte.cas_rn); wmrd:cas_rn; epar4:cas_rn; sxsamp:CASNumber (isotope labels on surrogate rows, not numeric CAS) |
| ResultFraction | Env_AnalyticalResults | wqx:ResultSampleFractionText; mining:Sample_Fraction (PK component); wmrd:fraction (PK component); epar4:total_or_dissolved (PK component) |
| QCType | Env_AnalyticalResults | wqx:ActivityTypeCode (the ONLY WQX QC discriminator); mining:Sample_Type + Sample_Source + Result_Type_Code; wmrd:sample_type_code + result_type_code (TRG/SUR); epar4:sample_type_code + result_type_code (TRG/SUR/TIC/IS/SC); sxsamp:SURROGATE flag + SampleID pattern (-BLK1/-BS1/-BS2) |
| MethodDilutionKey | Env_AnalyticalResults | wqx:SubstanceDilutionFactor; mining:Dilution_Factor + Test_Type; wmrd:dilution_factor + test_type + column_number; epar4:dilution_factor + test_type + column_number; sxsamp:Dilution |
| MethodID | Env_AnalyticalResults | wqx:ResultAnalyticalMethod/MethodIdentifier; mining:Analytical_Method_ID; wmrd:lab_anl_method_name; epar4:lab_anl_method_name |
| MethodName | Env_AnalyticalResults | wqx:ResultAnalyticalMethod/MethodName; sxsamp:Method ('EPA Method 1633') |
| AnalysisDate | Env_AnalyticalResults | wqx:AnalysisStartDate(+Time); mining:Analysis_Date (PK); wmrd:analysis_date; epar4:analysis_date+analysis_time (PK); sxsamp:DateAnalyzed |
| LimitType | Env_AnalyticalResults | wqx:DetectionQuantitationLimitTypeName (mandatory when a limit is given; routes WQX's generic limit value to ReportingLimit vs DetectionLimit at load) |
| ReportingLimit (existing) | Env_AnalyticalResults | wqx:DetectionQuantitationLimitMeasure/MeasureValue (routed by TypeName); mining:Lower_Reporting_Limit; wmrd:reporting_detection_limit; epar4:reporting_detection_limit; sxsamp:RL |
| DetectionLimit (existing) | Env_AnalyticalResults | mining:Method_Detection_Limit; wmrd:method_detection_limit; epar4:method_detection_limit; sxsamp:MDL (and EDL, unpopulated, LimitType='EDL') |
| ParentSampleID (existing) | Env_Samples/Env_AnalyticalResults | mining:Parent_Sample_ID; wmrd:parent_sample_code; epar4:parent_sample_code |
| LabSampleID (existing) | Env_Samples | mining:Lab_Sample_ID; wmrd:lab_sample_id; epar4:lab_sample_id; sxsamp:REDACTEDSampleID (legible suffix); wqx:SampleContainerLabelName (nearest equivalent, weak) |
| PrepBatchID | Env_QCResults | wmrd:Batch_v1.test_batch_id where test_batch_type=Prep; epar4:test_batch_id + test_batch_type=Prep; mining:Lab_Batch_ID + Batch_Type=PREP; sxsamp:REDACTEDQCBatch (single batch id - populate both batch fields) |
| AnalysisBatchID | Env_QCResults | mining:Lab_Batch_ID (Batch_Type default ANALYSIS); wmrd:Batch_v1.test_batch_id where test_batch_type=Analysis; epar4:test_batch_id + test_batch_type=Analysis; sxsamp:REDACTEDQCBatch (same value as prep) |
| QCType | Env_QCResults | mining:Sample_Source+Sample_Type+Result_Type_Code; wmrd:sample_type_code (QC-LD/LMS/LMSD/LCS/LCSD/LB...) + result_type_code; epar4:sample_type_code + result_type_code; sxsamp:SURROGATE='Y' + SampleID suffix (-BLK1/-BS1/-BS2) |
| ParentSampleID | Env_QCResults | mining:Parent_Sample_ID; wmrd:parent_sample_code; epar4:parent_sample_code |
| SpikeAmount | Env_QCResults | mining:qc_spike_added; wmrd:qc_spike_added; epar4:qc_spike_added (+qc_dup_spike_added on the pivoted MSD/LCSD row) |
| PercentRecovery | Env_QCResults | mining:qc_spike_recovery/qc_dup_spike_recovery; wmrd:qc_spike_recovery/qc_dup_spike_recovery; epar4:qc_spike_recovery/qc_dup_spike_recovery; sxsamp:Recovery |
| RecoveryLowerLimit / RecoveryUpperLimit | Env_QCResults | mining:qc_spike_lcl/qc_spike_ucl; wmrd:qc_spike_lcl/qc_spike_ucl; epar4:qc_spike_lcl/qc_spike_ucl; sxsamp:LCL/UCL |
| ResultNumeric / Units / AnalyteCanonicalName / Matrix / ImportBatchID / SiteID / provenance trio | Env_QCResults | all formats (ResultNumeric additionally receives qc_spike_measured for spike rows - documented convention; epar4's own dictionary proposed exactly this mapping) |

### Amendments (14)

Tagged with Step-1 disposition under the minimal boundary: **[STEP 1]** = WQX-populated, freeze now; **[STEP 3]** = no Step-2 producer, deferred (recorded so Step 3 does not re-derive). *These tags are heuristic (by presence of a WQX driver); the amended Step-1 spec's frozen list is authoritative — notably `SampleEndDate`/`SampleDuration`/`AirVolume` are deferred with the VI fields despite a WQX `ActivityEnd*` driver.*

- **[STEP 3]** `[add]` **Env_AnalyticalResults::QuantitationLimit (DOUBLE)**
  - A single EQuIS result row carries MDL + RL + PQL/LOQ simultaneously (three concurrent limit values). Two limit columns plus one LimitType discriminator structurally cannot hold a third concurrent value - the PQL would be silently dropped on every mining/wmrd/epar4 import. LimitType is kept for routing WQX's single generic limit.
  - drivers: mining:Quantitation_Limit, wmrd:quantitation_limit, epar4:quantitation_limit
- **[STEP 3]** `[add]` **Env_AnalyticalResults::IsReportable (SHORT)**
  - Three formats mark exactly one row per analyte as the reportable one (disambiguating dilution/reanalysis reruns). This spec's own required deliverable - the canonical-read helper that resolves to a single canonical row - needs this flag to pick correctly among MethodDilutionKey-distinct reruns; without it the helper must guess.
  - drivers: mining:Reportable_Result (required, default Y), wmrd:reportable_result, epar4:reportable_result (required)
- **[STEP 1]** `[add]` **Env_AnalyticalResults::LabName (TEXT)**
  - Four formats produce a per-result lab identifier, including WQX's real PhysChem export where LaboratoryName is in the confirmed load-bearing populated subset - meaning step 2 (the very next step) produces it immediately, not just step 3.
  - drivers: wqx:LaboratoryName (populated in the real USGS export), mining:Lab_Name, wmrd:lab_name_code, epar4:lab_name_code
- **[STEP 1]** `[add]` **Env_AnalyticalResults::PrepMethodID (TEXT) + PrepDate (DATE)**
  - Five of five formats carry lab prep/extraction method and/or date. Also corrects a concrete mis-mapping in the WQX dictionary (LabSamplePreparationMethod/MethodIdentifier -> MethodID), which would silently overwrite the analytical method with the prep method. Prep detail is the only batch-adjacent signal WQX has (no batch id exists there).
  - drivers: wqx:LabSamplePreparationMethod/MethodIdentifier + PreparationStartDate, mining:Prep_Method + Prep_Date, wmrd:prep_method + prep_date, epar4:lab_prep_method_name + prep_date/prep_time, sxsamp:DateExtracted
- **[STEP 1]** `[add]` **Env_AnalyticalResults::ResultBasis (TEXT)**
  - Near-universal (5/5 formats). Wet-weight vs dry-weight-adjusted changes what ResultNumeric means for every soil/tissue result; without it a dry-wt and wet-wt number are indistinguishable and screening comparisons are silently wrong. Data field only, NOT added to the unique key - dual-reported wet+dry rows are deduplicated via the MethodDilutionKey fold convention (see convention amendment).
  - drivers: wqx:ResultWeightBasisText, mining:Basis (wet_dry_na), wmrd:basis (WET/DRY/NA), epar4:basis, sxsamp:Basis (Dry Wt Adjusted\|Wet Wt)
- **[STEP 1]** `[add]` **Env_AnalyticalResults::MethodSpeciation (TEXT)**
  - Speciation (as N / as P / as CaCO3) changes the numeric meaning of the same CharacteristicName - a WQX step-2 concern, not just step 3. Companion convention (key safety without widening): where speciation is populated, AnalyteCanonicalName MUST incorporate it (e.g. 'Nitrate as N'), so as-N vs as-NO3 rows of the same characteristic never collide in the frozen key.
  - drivers: wqx:MethodSpeciationName, mining:Method_Speciation
- **[STEP 1]** `[convention]` **Env_AnalyticalResults::MethodDilutionKey (composite definition - document in the ADR)**
  - wmrd/epar4 result identity includes column_number (dual-column GC: two legitimate rows per analyte differing only in column) and test_type (INITIAL/DILUTION/REANALYSIS/REEXTRACT); WQX adds StatisticalBaseCode and dual-basis rows. None of these have a key column, and the key can never be widened. Define MethodDilutionKey as the deterministic composite run-discriminator built by readers from: dilution factor + test_type + GC column_number + any residual same-analyte splitting dimension (statistic base, basis when dual-reported). Deterministic from source data, defaults to "" - preserves idempotency.
  - drivers: wmrd:column_number+test_type (PK components), epar4:column_number+test_type (PK components), mining:Test_Type, wqx:StatisticalBaseCode
- **[STEP 3]** `[add]` **Env_QCResults::SampleID (TEXT) - the QC sample's own identifier**
  - The proposed QC table has NO identity column for the QC sample itself, yet every format assigns one (sxsamp 'B26F056-BS1'/'-BLK1'; mining/wmrd/epar4 QC samples carry their own sys_sample_code/Sample_ID). Without it, surrogate recoveries - one per FIELD sample per batch - are indistinguishable, and you cannot tell BS1 from BS2. Required both as data and as a key component (see key-change).
  - drivers: sxsamp:SampleID (B26F056-BS1/-BS2/-BLK1), wmrd:sys_sample_code (lab-source samples), mining:Sample_ID (Sample_Source=Lab), epar4:sys_sample_code
- **[STEP 3]** `[add]` **Env_QCResults::ResultRawText, ReportingLimit, DetectionLimit, Qualifier, IsNonDetect, AnalyteName, CASNumber, LabSampleID, AnalysisDate**
  - Method-blank rows ARE non-detect results with limits: sxsamp BLK1 rows report Concentration='ND' + MDL + RL; wmrd/mining method blanks likewise ride the normal result columns. The proposed field list (ResultNumeric/Units only) cannot represent a blank result at all. Every format also reports the raw analyte name, CAS, lab sample id and analysis date on QC rows - parity with Env_AnalyticalResults costs nothing and avoids a second irreversible add-round under different names.
  - drivers: sxsamp:Concentration('ND')+MDL+RL+Qualifiers on BLK/BS rows, wmrd:result_value/detect_flag/lab_qualifiers on QC rows, mining:Result_Value/Detect_Flag/Lab_Qualifiers, epar4:same columns on RES rows
- **[STEP 3]** `[add]` **Env_QCResults::OriginalConcentration (DOUBLE), RPD (DOUBLE), RPDControlLimit (DOUBLE)**
  - Produced by all three EQuIS dialects (qc_original_conc, qc_rpd, qc_rpd_cl) and present in the sxsamp schema (RPD/RPDCL columns, unpopulated in this export). Needed to represent MS/MSD and LCS/LCSD pairs: the wide qc_dup_* columns pivot to a second row (QCType=MSD/LCSD) reusing SpikeAmount/PercentRecovery/these fields - that pivot is the documented load convention.
  - drivers: mining:qc_original_conc/qc_rpd/qc_rpd_cl, wmrd:qc_original_conc/qc_rpd/qc_rpd_cl, epar4:qc_original_conc/qc_rpd/qc_rpd_cl, sxsamp:RPD/RPDCL (schema columns)
- **[STEP 3]** `[add]` **Env_QCResults::MethodID, ResultFraction, MethodDilutionKey**
  - Source QC-row identity in wmrd/epar4 is (sys_sample_code, lab_anl_method_name, fraction, column_number, test_type, cas_rn). Without method/fraction/run discriminators the QC table cannot distinguish a blank's ICP-MS run from its mercury run, or an initial from a diluted QC re-run - same collision class the spec already fixed on Env_AnalyticalResults, so mirror the same three fields.
  - drivers: wmrd:lab_anl_method_name+fraction+column_number+test_type (Batch_v1/TestResultQC_v1 join key), epar4:lab_anl_method_name+total_or_dissolved+test_type (PK components), mining:Analytical_Method_ID+Sample_Fraction (PK components)
- **[STEP 3]** `[key-change]` **Env_QCResults::UNIQUE_KEYS['Env_QCResults']**
  - Two demonstrated collisions under the proposed 5-field key: (a) sxsamp surrogate rows - EVERY sample in batch B26F056 has a 13C4-PFBA recovery, all yielding the identical (Site,Matrix,Batch,Analyte,QCType='surrogate') tuple, so all but one would be silently dropped; (b) two MS/MSD pairs on different parent samples within one batch (permitted by all three EQuIS dialects) collide without the QC sample's own SampleID. ResultFraction/MethodID/MethodDilutionKey mirror the source PKs (see field-add rationale). All new components default "" per the spec's discriminator-defaults rule. Load convention: single-batch-id formats (sxsamp, mining) populate BOTH PrepBatchID and AnalysisBatchID with the one id, so AnalysisBatchID is never empty in the key.
  - drivers: sxsamp, wmrd, epar4, mining
- **[STEP 3]** `[regrain]` **Env_Samples (VI fields)::VI building-survey attributes (building_type, foundation_type, heat_fuel_type, num_floors, construct_year, ...)**
  - The spec froze ALL VI fields as Env_Samples-grain, but EPAR4 proves two distinct grains: per-sample vapor-collection attributes (VI_Samples_v1 - genuinely sample-grain, freeze on Env_Samples now, see vi_fields_final) versus building-inspection attributes keyed (building_code, inspection_date) with satellite VI_Building_Parameters_v1 and VI_Bldg_Address_v1 tables (WMRD's ~40-enum building survey is the same entity). A building spans many samples across many events, inspections have their own dates, and inspected buildings can have zero samples - denormalizing 30-57 inspection fields onto every sample row loses the inspection identity and cannot represent sample-less inspections. Building-survey fields must NOT freeze onto Env_Samples. Deferring them entirely is SAFE under the additive-only model (new tables can always be added later): defer a future Env_VIBuildingSurveys table keyed (SiteID, BuildingCode, InspectionDate) to step 3's spec.
  - drivers: epar4:VI_Building_Inspection_v1 PK=(building_code,inspection_date) + VI_Building_Parameters_v1 + VI_Bldg_Address_v1, wmrd:VI_BuildingInspection_v1 (enum-defined)
- **[STEP 1]** `[add]` **Env_Samples::SampleEndDate (DATE), SampleDuration (TEXT), SampleDurationUnits (TEXT), AirVolume (TEXT), AirVolumeUnits (TEXT)**
  - Duration/canister vapor sampling (24-hr Summa) and WQX activities both carry an end date and duration; these are sample-grain and needed the moment any air/vapor EDD is imported. Producers span 2-3 formats.
  - drivers: epar4:sample_end_date/sample_duration(+unit)/duration(+unit)/air_volume(+unit), wqx:ActivityEndDate/ActivityEndTime

### Finalized Env_QCResults field list (DEFERRED to Step 3 - recorded for reuse)

The synthesis finalized this table's shape; under the minimal boundary it is **not created in Step 1** (WQX has no QC concept). Step 3 creates it and verifies these names against real EQuIS QC data:

- ImportBatchID (TEXT 64)
- SiteID (TEXT 32)
- Matrix (TEXT 16)
- PrepBatchID (TEXT 64)
- AnalysisBatchID (TEXT 64)
- QCType (TEXT 32)
- SampleID (TEXT 64) - the QC sample's own id (B26F056-BS1 / lab-source sys_sample_code; for surrogate rows, the field sample's id)
- ParentSampleID (TEXT 64)
- LabSampleID (TEXT 64)
- AnalyteName (TEXT 128)
- AnalyteCanonicalName (TEXT 128)
- CASNumber (TEXT 32)
- MethodID (TEXT 64)
- ResultFraction (TEXT 32)
- MethodDilutionKey (TEXT 64)
- AnalysisDate (DATE)
- ResultRawText (TEXT 64)
- ResultNumeric (DOUBLE) - also receives qc_spike_measured on spike rows (documented convention)
- Units (TEXT 16)
- ReportingLimit (DOUBLE)
- DetectionLimit (DOUBLE)
- Qualifier (TEXT 16)
- IsNonDetect (SHORT)
- SpikeAmount (DOUBLE)
- OriginalConcentration (DOUBLE)
- PercentRecovery (DOUBLE)
- RecoveryLowerLimit (DOUBLE)
- RecoveryUpperLimit (DOUBLE)
- RPD (DOUBLE)
- RPDControlLimit (DOUBLE)
- SourceWorkbook (TEXT 255)
- SourceSheet (TEXT 64)
- SourceRow (LONG)

Proposed `UNIQUE_KEYS['Env_QCResults']` (Step 3): `SiteID, Matrix, AnalysisBatchID, SampleID, QCType, AnalyteCanonicalName, ResultFraction, MethodID, MethodDilutionKey`

### Finalized VI field list (DEFERRED to Step 3 - recorded for reuse)

Building-survey attributes are `(building_code, inspection_date)`-grain, NOT `Env_Samples`-grain - a **regrain** of spec section 7. They belong in a future additive `Env_VIBuildingSurveys` table (Step 3). The VI sample/duration fields also defer:

- - Env_Samples-grain vapor/duration-sampling fields (producers: epar4 VI_Samples_v1 + EPAR4_FSample_v1; wmrd VI_Samples enum-referenced; wqx ActivityEnd*) -
- SampleEndDate (DATE)
- SampleDuration (TEXT 20)
- SampleDurationUnits (TEXT 15)
- AirVolume (TEXT 15)
- AirVolumeUnits (TEXT 15)
- VIFloorMaterial (TEXT 20)
- VISlabThickness (TEXT 20)
- VISubslabMaterial (TEXT 20)
- VISubslabMoisture (TEXT 20)
- VISealType (TEXT 20)
- VISealAdequate (SHORT)
- VIPurgePerformed (SHORT)
- VIPurgePID (DOUBLE)
- VIPurgePIDUnits (TEXT 15)
- VIVacuumInitial (DOUBLE)
- VIVacuumFinal (DOUBLE)
- VIVacuumUnits (TEXT 15)
- VIVaporLocationDesc (TEXT 255)
- VITracerTestConducted (SHORT)
- - Building-survey attributes (building_type, foundation_type, heat_fuel_type, etc.) are EXCLUDED from Env_Samples per the regrain amendment: they are (building_code, inspection_date)-grain; a future additive Env_VIBuildingSurveys table is deferred to step 3 (safe - new tables carry no rename risk) -

### Frozen unique key - Env_AnalyticalResults (STEP 1)

`SiteID, Matrix, LocationID, SampleID, SampleDate, AnalyteCanonicalName, DepthIntervalText, SourceCell, ResultFraction, QCType, MethodDilutionKey`

11 components (ResultBasis folded into `MethodDilutionKey`, not added as a 12th).

### Unmapped source fields (20) - dispositions

- **mining, wmrd, epar4, wqx, sxsamp::quantitation_limit / Basis / reportable_result / lab name / prep method+date / speciation** [result] - add - covered by the amendments above (QuantitationLimit, ResultBasis, IsReportable, LabName, PrepMethodID/PrepDate, MethodSpeciation).
- **4 formats::percent_moisture (mining/wmrd/epar4) + PercentSolidsLipids (sxsamp)** [result] - defer - data-only, no near-term consumer; additive model allows adding PercentMoisture later without rename risk. Note sxsamp reports percent SOLIDS, not moisture (not a trivial inverse for lipids).
- **mining, wmrd, epar4::detection_limit_unit** [result] - defer - load-time policy instead: convert limits to result units where possible, QA-WARN on mismatch. Add a DetectionLimitUnits column later only if real data shows unconvertible mismatches.
- **wmrd, epar4 (+mining Interpreted_Qualifiers)::validator_qualifiers / interpreted_qualifiers / validated_yn / validation_level** [result] - defer, with a documented convention NOW (no schema change): Qualifier holds the final/interpreted qualifier where the format distinguishes, else the lab qualifier. Add ValidatorQualifier later if a data-validation workflow lands.
- **wmrd, epar4, sxsamp (Analyst)::analyst_name / instrument_id** [result] - drop - lab-internal provenance no current or planned tool consumes; recoverable from source files via the provenance trio.
- **wmrd, epar4, sxsamp::sample_delivery_group / lab_sdg / ClientProjectName (work order)** [sample] - defer - useful provenance (ties samples to the lab report) but SourceWorkbook already anchors the file; add an SDG column later if lab-report-level QA tooling appears.
- **wmrd, epar4, sxsamp (DateReceived)::chain_of_custody / sent_to_lab_date / sample_receipt_date(+time)** [sample] - defer - the natural consumer is holding-time QC tooling that doesn't exist yet; safe to add later.
- **mining, wmrd, epar4::sampler / sampling_company_code / sampling_reason / sample_method / sampling_technique** [sample] - defer - field-collection metadata with no consumer; sampling_company was REDACTED (PII) in WMRD source.
- **mining, wmrd, epar4::composite_yn / composite_desc** [sample] - defer.
- **mining, wmrd, epar4::leachate_method / leachate_date** [result] - defer - leachate workflows not in scope; when added, note Lab_Matrix (leachate) already folds into Matrix via value_maps.
- **mining, wmrd, epar4::Test_Type / column_number (as standalone columns)** [result] - fold into MethodDilutionKey per the convention amendment - do NOT add columns; they are run discriminators, not analytical values.
- **3 formats::Medium (mining) / lab_matrix_code (wmrd, epar4)** [sample/result] - fold into Matrix via the spec's value_maps generalization; no new field.
- **wmrd, epar4, sxsamp::radiochem set: result_error_delta, minimum_detectable_conc, counting_error, uncertainty, critical_value; EMPC (sxsamp, unpopulated)** [result] - defer - radiochem is not in this practice's workflow; sxsamp EMPC was schema-only/unpopulated. EDL maps to DetectionLimit with LimitType='EDL' (no new field).
- **wqx::WQX StatisticalBaseCode / StatisticalNValueNumeric / ResultTimeBasisText / ResultTemperatureBasisText** [result] - defer; if statistical WQX rows are ever imported, StatisticalBaseCode folds into MethodDilutionKey (convention) to prevent Mean-vs-Max key collisions.
- **mining, wmrd, epar4::qc_spike_status / qc_dup_spike_status / qc_rpd_status ('*' flags)** [qc] - drop - deterministically derivable from PercentRecovery/RPD vs the stored control limits; deriving at read beats storing a redundant flag.
- **wmrd, epar4::qc_level (SCREEN/QUANT) / analysis_location (FI/FL/LB)** [result] - defer.
- **mining, wmrd(enum), epar4::SampleParameter sheets (param_code/param_value field measurements) + FieldCollection/FieldResults field-parameter rows** [sample/result] - defer the routing decision to step 3's reader spec - they flatten cleanly into Env_AnalyticalResults as ordinary results (AnalyteName=parameter, MethodID=measurement_method), no schema change required.
- **epar4::VI COC/container logistics (VI_COC, VI_COC_Analysis, VI_COC_Container ~86 fields) + cooler_temp/holding_time/lab_security_seal** [other] - drop (per the extractor's own DROP marks); revisit cooler_temp/holding_time only if holding-time QC tooling is ever built.
- **wmrd, wqx, epar4::#data_provider / DataProviderCode / OrganizationIdentifier / ProviderName** [other] - drop - SourceWorkbook + ImportBatchID already anchor provenance; org identity is derivable from the source file.
- **wmrd, epar4, wqx, mining::sample_name (human name w/o lab suffix) / MonitoringLocationName / Station_Name** [sample/location] - defer - location-name belongs to the location tables (out of this pass's scope); sample_name usually equals LabSampleID in practice (WMRD confirms equality).

### Original open questions - resolutions

1. Only 5 of the 6 named formats had dictionaries supplied - NYSDEC v5 EDD is missing. It is a close EQuIS cousin of WMRD/EPAR4 (its 65-column TestResultQC_v5 almost certainly matches the qc_*/batch pattern reconciled here), but spot-check it against the final field list before the freeze is implemented, since the spec explicitly names it as a step-3 dialect.
2. VI scope confirmation: does the practice actually intend to ingest VI building-inspection surveys? If yes, the deferred Env_VIBuildingSurveys table (building_code + inspection_date grain) should get its own paper mapping in step 3's spec; if no, nothing further is needed - deferral is safe either way under additive-only.
3. sxsamp BS1/BS2 semantics: are they an LCS/LCSD pair (QCType=LCS/LCSD) or two independent LCS? Affects the QCType value_map for this lab only, not the schema; the widened key (SampleID included) is collision-safe under either reading.
4. Qualifier semantics convention: confirm 'Qualifier = final/interpreted qualifier where the format distinguishes lab vs validator vs interpreted; lab qualifier otherwise' - the alternative (Qualifier = raw lab flags, add InterpretedQualifier later) is equally freezable but must be picked once, now, because downstream IsEstimated derivation reads it.
5. ResultBasis dedup policy: accept the fold-into-MethodDilutionKey convention for the rare dual-reported wet+dry pair (recommended), or add ResultBasis to the Env_AnalyticalResults key as a 12th component? The key can never be widened later - this is the only remaining dimension I judged fold-worthy rather than key-worthy, and it deserves an explicit human sign-off.
6. Limit-unit policy: confirm 'convert detection/reporting/quantitation limits to result units at load, QA-WARN on unconvertible mismatch' in lieu of a DetectionLimitUnits column (deferrable additively if real data breaks the assumption).

**Resolutions:** Q1 (NYSDEC) -> deferred to Step 3 per minimal boundary. Q2 (VI scope) -> deferred (VI table is Step 3, additive-safe either way). Q3/Q4/Q5/Q6 -> per the decision table above.
