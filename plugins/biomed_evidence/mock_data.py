from __future__ import annotations

from plugins.biomed_evidence.schemas import (
    BiomedicalEntity,
    BiomedicalPaper,
    EvidenceItem,
)

MOCK_PAPERS: list[BiomedicalPaper] = [
    BiomedicalPaper(
        paper_id="MOCK-PMID-1001",
        source="mock",
        title=(
            "Microglial activation signatures track Alzheimer's disease progression "
            "in human single-nucleus transcriptomes"
        ),
        abstract=(
            "Single-nucleus RNA sequencing of post-mortem human cortex identified "
            "disease-associated microglia with increased complement and inflammatory "
            "programs. The abundance of activated microglia correlated with Braak "
            "stage and amyloid pathology, although the cross-sectional design limits "
            "causal interpretation."
        ),
        authors=["A. Jensen", "M. Lindberg", "S. Patel"],
        journal="Mock Journal of Neuroinflammation",
        publication_date="2025-02-14",
        doi="10.0000/mock.1001",
        url="https://pubmed.ncbi.nlm.nih.gov/1001/",
        mesh_terms=["Alzheimer Disease", "Microglia", "Neuroinflammation"],
        keywords=["microglia", "Alzheimer's disease", "single-nucleus RNA-seq"],
    ),
    BiomedicalPaper(
        paper_id="MOCK-PMID-1002",
        source="mock",
        title="TREM2-dependent microglial states associate with amyloid plaque neighborhoods",
        abstract=(
            "Spatial transcriptomics and immunostaining showed enrichment of TREM2 "
            "positive microglia around amyloid plaques. Gene modules related to lipid "
            "handling and phagocytosis were linked to local plaque burden, but samples "
            "were limited to a small donor cohort."
        ),
        authors=["L. Holm", "R. Chen"],
        journal="Mock Spatial Biology",
        publication_date="2024-11-03",
        doi="10.0000/mock.1002",
        url="https://pubmed.ncbi.nlm.nih.gov/1002/",
        mesh_terms=["TREM2", "Amyloid beta-Peptides", "Microglia"],
        keywords=["TREM2", "spatial transcriptomics", "amyloid plaque"],
    ),
    BiomedicalPaper(
        paper_id="MOCK-PMID-1003",
        source="mock",
        title="Longitudinal CSF markers suggest neuroinflammation precedes cognitive decline",
        abstract=(
            "A longitudinal cohort study found that cerebrospinal fluid inflammatory "
            "markers and microglial activation-associated proteins preceded measurable "
            "cognitive decline in a subset of participants. Associations weakened after "
            "adjustment for vascular comorbidity, making the evidence inconclusive."
        ),
        authors=["D. Williams", "N. Okafor", "E. Shah"],
        journal="Mock Alzheimer's Research",
        publication_date="2023-08-19",
        doi="10.0000/mock.1003",
        url="https://pubmed.ncbi.nlm.nih.gov/1003/",
        mesh_terms=["Cerebrospinal Fluid", "Cohort Studies", "Cognitive Dysfunction"],
        keywords=["CSF", "neuroinflammation", "cohort"],
    ),
    BiomedicalPaper(
        paper_id="MOCK-PMID-1004",
        source="mock",
        title="Anti-inflammatory mouse model findings do not fully translate to human Alzheimer's cohorts",
        abstract=(
            "In a transgenic mouse model, pharmacological suppression of microglial "
            "activation reduced inflammatory gene expression but did not improve "
            "memory outcomes. The study cautions that animal-model effects may "
            "contradict or fail to predict human disease progression."
        ),
        authors=["P. Alvarez", "K. Ito"],
        journal="Mock Translational Neuroscience",
        publication_date="2022-05-27",
        doi="10.0000/mock.1004",
        url="https://pubmed.ncbi.nlm.nih.gov/1004/",
        mesh_terms=["Disease Models, Animal", "Microglia", "Alzheimer Disease"],
        keywords=["mouse model", "microglial activation", "translation"],
    ),
    BiomedicalPaper(
        paper_id="MOCK-PMID-2001",
        source="mock",
        title="Spatial transcriptomics resolves tumor microenvironment niches in melanoma",
        abstract=(
            "Spatial transcriptomics of melanoma biopsies identified immune-suppressed "
            "tumor microenvironment niches with exhausted T cells, macrophage programs, "
            "and stromal signaling. Findings require validation in larger cohorts."
        ),
        authors=["H. Sørensen", "J. Lee"],
        journal="Mock Cancer Atlas",
        publication_date="2025-01-09",
        doi="10.0000/mock.2001",
        url="https://pubmed.ncbi.nlm.nih.gov/2001/",
        mesh_terms=["Melanoma", "Tumor Microenvironment", "Spatial Transcriptomics"],
        keywords=["spatial transcriptomics", "tumor microenvironment", "melanoma"],
    ),
]


MOCK_EVIDENCE: dict[str, list[EvidenceItem]] = {
    "MOCK-PMID-1001": [
        EvidenceItem(
            evidence_id="ev-mock-1001-1",
            paper_id="MOCK-PMID-1001",
            claim=(
                "Activated microglial transcriptional states are associated with "
                "Alzheimer's disease progression markers."
            ),
            finding=(
                "Disease-associated microglia were enriched in higher Braak stage "
                "samples and correlated with amyloid pathology."
            ),
            evidence_direction="supports",
            entities=[
                BiomedicalEntity(name="microglia", entity_type="cell_type"),
                BiomedicalEntity(name="Alzheimer's disease", entity_type="disease"),
                BiomedicalEntity(name="neuroinflammation", entity_type="pathway"),
            ],
            methods=["single-nucleus RNA-seq"],
            datasets_or_cohorts=["post-mortem human cortex cohort"],
            limitations=["Cross-sectional design limits causal interpretation."],
            confidence="high",
            evidence_span=(
                "The abundance of activated microglia correlated with Braak stage "
                "and amyloid pathology"
            ),
            requires_expert_review=True,
        )
    ],
    "MOCK-PMID-1002": [
        EvidenceItem(
            evidence_id="ev-mock-1002-1",
            paper_id="MOCK-PMID-1002",
            claim="TREM2-positive microglia localize around amyloid plaques.",
            finding=(
                "Spatial transcriptomics and immunostaining found TREM2 positive "
                "microglia enriched around plaque neighborhoods."
            ),
            evidence_direction="supports",
            entities=[
                BiomedicalEntity(name="TREM2", entity_type="gene"),
                BiomedicalEntity(name="microglia", entity_type="cell_type"),
                BiomedicalEntity(name="amyloid plaques", entity_type="pathway"),
            ],
            methods=["spatial transcriptomics", "immunostaining"],
            datasets_or_cohorts=["small post-mortem donor cohort"],
            limitations=["Small donor cohort limits generalizability."],
            confidence="medium",
            evidence_span="TREM2 positive microglia around amyloid plaques.",
            requires_expert_review=True,
        )
    ],
    "MOCK-PMID-1003": [
        EvidenceItem(
            evidence_id="ev-mock-1003-1",
            paper_id="MOCK-PMID-1003",
            claim=(
                "Microglial activation-associated CSF proteins may precede cognitive "
                "decline in some participants."
            ),
            finding=(
                "Longitudinal associations were observed, but effect estimates "
                "weakened after vascular-comorbidity adjustment."
            ),
            evidence_direction="inconclusive",
            entities=[
                BiomedicalEntity(name="microglial activation", entity_type="pathway"),
                BiomedicalEntity(name="cognitive decline", entity_type="disease"),
                BiomedicalEntity(name="CSF", entity_type="dataset"),
            ],
            methods=["longitudinal cohort study", "CSF proteomics"],
            datasets_or_cohorts=["longitudinal CSF cohort"],
            limitations=["Associations weakened after confounder adjustment."],
            confidence="medium",
            evidence_span="Associations weakened after adjustment for vascular comorbidity",
            requires_expert_review=True,
        )
    ],
    "MOCK-PMID-1004": [
        EvidenceItem(
            evidence_id="ev-mock-1004-1",
            paper_id="MOCK-PMID-1004",
            claim=(
                "Reducing microglial inflammatory activation in a mouse model did not "
                "improve memory outcomes."
            ),
            finding=(
                "Inflammatory gene expression decreased, but memory outcomes did not "
                "improve, limiting translation to human progression."
            ),
            evidence_direction="contradicts",
            entities=[
                BiomedicalEntity(name="microglia", entity_type="cell_type"),
                BiomedicalEntity(name="Alzheimer's disease", entity_type="disease"),
                BiomedicalEntity(name="mouse model", entity_type="organism"),
            ],
            methods=["transgenic mouse model", "pharmacological perturbation"],
            datasets_or_cohorts=["animal model experiment"],
            limitations=["Animal model may not predict human disease progression."],
            confidence="medium",
            evidence_span="did not improve memory outcomes",
            requires_expert_review=True,
        )
    ],
    "MOCK-PMID-2001": [
        EvidenceItem(
            evidence_id="ev-mock-2001-1",
            paper_id="MOCK-PMID-2001",
            claim=(
                "Spatial transcriptomics can identify immune and stromal niches in "
                "the tumor microenvironment."
            ),
            finding=(
                "Melanoma biopsies contained immune-suppressed spatial niches with "
                "exhausted T cells, macrophage programs, and stromal signaling."
            ),
            evidence_direction="supports",
            entities=[
                BiomedicalEntity(name="tumor microenvironment", entity_type="disease"),
                BiomedicalEntity(name="T cells", entity_type="cell_type"),
                BiomedicalEntity(name="macrophage", entity_type="cell_type"),
            ],
            methods=["spatial transcriptomics"],
            datasets_or_cohorts=["melanoma biopsy cohort"],
            limitations=["Requires validation in larger cohorts."],
            confidence="high",
            evidence_span="immune-suppressed tumor microenvironment niches",
            requires_expert_review=True,
        )
    ],
}
