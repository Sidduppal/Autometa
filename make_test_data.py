#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
COPYRIGHT
Copyright 2020 Ian J. Miller, Evan R. Rees, Kyle Wolf, Siddharth Uppal,
Shaurya Chanana, Izaak Miller, Jason C. Kwan

This file is part of Autometa.

Autometa is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Autometa is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with Autometa. If not, see <http://www.gnu.org/licenses/>.
COPYRIGHT

1. Generate all files and intermediates for corresponding to *one* metagenome
    2. Retrieve intermediate files related to each stage:
        2.1 metagenome
            2.1.1 length filtered
            2.1.2 called orfs
        2.2 kmers
            2.2.1 counts
            2.2.2 normalized counts
        2.3 coverage
            2.3.1 from spades names
            2.3.2 from reads
            2.3.3 from sam
            2.3.4 from bam
            2.3.5 from bed
        2.4 markers
            2.4.1 orfs to scan
            2.4.2 hmmscan output
            2.4.3 filtered hmmscan output
        2.5 taxonomy
            2.5.1 orfs
            2.5.2 blastp
            2.5.3 prot.accession2taxid
            2.5.4 nodes
            2.5.5 names
            2.5.6 merged
        2.6 binning
            2.6.1 kmers
            2.6.2 coverage
            2.6.3 markers
            2.6.4 taxonomy

Make test_data.json to be used to ensure autometa was properly installed.
"""


import gzip
import json

import attr
import pandas as pd
from Bio import SeqIO

from autometa.common import kmers, markers
from autometa.common.external import hmmer, prodigal
from autometa.taxonomy.ncbi import NCBI
import logging
import os

logger = logging.getLogger(__name__)

logging.basicConfig(
    format="[%(asctime)s %(levelname)s] %(name)s: %(message)s",
    datefmt="%m/%d/%Y %I:%M:%S %p",
    level=logging.DEBUG,
)


def subset_acc2taxids(blastp_accessions: set, ncbi: NCBI) -> dict:
    acc2taxids = {}
    fh = (
        gzip.open(ncbi.accession2taxid_fpath, "rt")
        if ncbi.accession2taxid_fpath.endswith(".gz")
        else open(ncbi.accession2taxid_fpath)
    )
    fh.readline()  # skip reading header line
    for line in fh:
        acc_num, acc_ver, taxid, _ = line.split("\t")
        if acc_num in blastp_accessions:
            acc2taxids[acc_num] = taxid
        if acc_ver in blastp_accessions:
            acc2taxids[acc_ver] = taxid
    return acc2taxids


@attr.s(kw_only=True)
class TestData:
    metagenome = attr.ib(validator=attr.validators.instance_of(str))
    metagenome_nucl_orfs = attr.ib(validator=attr.validators.instance_of(str))
    metagenome_prot_orfs = attr.ib(validator=attr.validators.instance_of(str))
    markers_orfs = attr.ib(validator=attr.validators.instance_of(str))
    markers_scans = attr.ib(validator=attr.validators.instance_of(str))
    markers_filtered = attr.ib(validator=attr.validators.instance_of(str))
    taxonomy_ncbi = attr.ib(validator=attr.validators.instance_of(str))
    taxonmy_blastp = attr.ib(validator=attr.validators.instance_of(str))
    taxonomy_orfs = attr.ib(validator=attr.validators.instance_of(str))
    binning_norm_kmers = attr.ib(validator=attr.validators.instance_of(str))
    binning_embedded_kmers = attr.ib(validator=attr.validators.instance_of(str))
    binning_coverage = attr.ib(validator=attr.validators.instance_of(str))
    binning_markers = attr.ib(validator=attr.validators.instance_of(str))
    binning_taxonomy = attr.ib(validator=attr.validators.instance_of(str))
    data = attr.ib(factory=dict)
    seed = attr.ib(default=42)

    def get_kmers(self, num_records: int = 4):
        if num_records < 4:
            raise ValueError(
                f"At least 4 records are required for embedding tests! provided: {num_records}"
            )
        logger.info("Preparing kmer counts test data...")
        # kmer size is 5 (b/c this is the default).
        counts = kmers.count(assembly=self.metagenome, size=5)
        # subset counts to first rows via `num_records`
        counts = counts.iloc[:num_records]
        # method is am_clr (b/c this is the default).
        am_clr_normalized_counts = kmers.normalize(df=counts, method="am_clr")
        logger.info("Preparing metagenome records test data...")
        records = {}
        for record in SeqIO.parse(self.metagenome, "fasta"):
            records.update({f">{record.id}": str(record.seq)})
            if len(records) >= num_records:
                break

        for df in [counts, am_clr_normalized_counts]:
            df.reset_index(inplace=True)
        self.data["kmers"] = {
            "counts": counts.to_json(),
            "am_clr_normalized_counts": am_clr_normalized_counts.to_json(),
        }
        self.data["metagenome"] = {"assembly": records}

    def get_markers(self):
        logger.info("Preparing orfs for markers annotation")
        try:
            prodigal.run(
                assembly=self.metagenome,
                nucls_out=self.metagenome_nucl_orfs,
                prots_out=self.metagenome_prot_orfs,
                force=False,
            )
        except FileExistsError:
            logger.debug("markers orfs already exist")
        markers_query_orfs = [
            record
            for record in SeqIO.parse(self.metagenome_prot_orfs, "fasta")
            if record.id == "NODE_1505_length_7227_cov_222.087_6"
        ]
        if not os.path.exists(self.markers_orfs):
            SeqIO.write(markers_query_orfs, self.markers_orfs, "fasta")
        markers_query_orfs = {f">{rec.id}": str(rec.seq) for rec in markers_query_orfs}
        logger.info("Annotating ORFs with single-copy markers")
        if not os.path.exists(self.markers_scans) or not os.path.exists(
            self.markers_filtered
        ):
            self.markers_filtered = (
                self.markers_filtered.replace(".gz", "")
                if self.markers_filtered.endswith(".gz")
                else self.markers_filtered
            )
            markers.get(
                kingdom="archaea",
                orfs=self.markers_orfs,
                dbdir=markers.MARKERS_DIR,
                scans=self.markers_scans,
                out=self.markers_filtered,
                seed=self.seed,
            )
        # Retrieve test output hmmscan table
        scans = pd.read_csv(self.markers_scans, sep="\s+", header=None, comment="#")
        filtered_markers = pd.read_csv(self.markers_filtered, sep="\t")
        # The ORFs are necessary for ORF to contig translations
        self.data["markers"] = {
            "scans": scans.to_json(),
            "filtered_markers": filtered_markers.to_json(),
            "orfs": markers_query_orfs,
        }

    def get_taxonomy(self, num_orfs: int = 2):
        logger.info("Making taxonomy test data...")
        # Get diamond blastp output table
        orf_column = 0
        blastp = pd.read_csv(
            self.taxonmy_blastp, sep="\t", index_col=orf_column, header=None
        )
        # Get number of unique ORFs set by `num_orfs`, default is 2.
        orf_hits = set(blastp.index.unique().tolist()[:num_orfs])
        blastp = blastp.loc[orf_hits]
        blastp.reset_index(inplace=True)
        if num_orfs == 2:
            # NODE_38_length_280079_cov_224.186_1 and NODE_38_length_280079_cov_224.186_2
            # together have 400 hits
            assert blastp.shape == (
                400,
                12,
            ), f"shape: {blastp.shape}\ncolumns: {blastp.columns}"

        blastp_query_orfs = {
            f">{record.id}": str(record.seq)
            for record in SeqIO.parse(self.taxonomy_orfs, "fasta")
            if not record.id in orf_hits
        }

        ncbi = NCBI(self.taxonomy_ncbi)
        # Get prot.accession2taxid datastructure and subset by taxids encountered in blastp output.
        sacc_column = 1
        blastp_accessions = set(blastp[sacc_column].unique().tolist())
        acc2taxids = subset_acc2taxids(blastp_accessions, ncbi)
        accessions = {k for k in acc2taxids.keys()}
        blastp = blastp.set_index(sacc_column).loc[accessions].reset_index()
        blastp = blastp.set_index(orf_column).reset_index()
        assert blastp.shape[0] == len(
            acc2taxids
        ), f"blastp shape: {blastp.shape}\tnum. acc2taxids: {len(acc2taxids)}"
        # Get nodes.dmp, names.dmp and merged.dmp data structures.
        nodes = ncbi.nodes
        names = ncbi.names
        # Merged are only necessary if taxids have been deprecated or suppressed
        blastp_taxids = acc2taxids.values()
        merged = {old: new for old, new in ncbi.merged.items() if old in blastp_taxids}

        self.data["taxonomy"] = {
            "prot_orfs": blastp_query_orfs,
            "blastp": blastp.to_json(),
            "acc2taxid": acc2taxids,
            "merged": merged,
            "nodes": nodes,
            "names": names,
        }

    def get_coverage(self):
        if "coverage" not in self.data:
            self.data["coverage"] = {
                "spades_records": self.metagenome,
                "bam": "alignments.bam",
                "sam": "alignments.sam",
            }
        return self.data["coverage"]

    def get_binning(self, num_contigs: int = 10):
        # Need kmers, coverage, markers, taxonomy
        logger.info("Preparing binning test data")
        annotations = {
            "kmers_normalized": self.binning_norm_kmers,
            "kmers_embedded": self.binning_embedded_kmers,
            "taxonomy": self.binning_taxonomy,
            "coverage": self.binning_coverage,
        }
        markers_df = pd.read_csv(self.binning_markers, sep="\t", index_col="contig")
        contigs = None
        for annotation, fpath in annotations.items():
            df = pd.read_csv(fpath, sep="\t", index_col="contig")
            # We'll grab the first `num_contigs` from the first dataframe (kmers)
            if not contigs:
                # We need to ensure the contigs we pull contain markers...
                contigs = set(
                    df[df.index.isin(markers_df.index)].index.tolist()[:num_contigs]
                )
            # We need to reset the index from contig to None before json export.
            jsonified = df.loc[contigs].reset_index().to_json()
            if "binning" not in self.data:
                self.data["binning"] = {annotation: jsonified}
            else:
                self.data["binning"].update({annotation: jsonified})
        markers_df.reset_index(inplace=True)
        self.data["binning"].update({"markers": markers_df.to_json()})

    def to_json(self, out: str):
        logger.info(f"Serializing data to {out}")
        with open(out, "w") as fh:
            json.dump(obj=self.data, fp=fh)
        logger.info(f"Wrote test data to {out}")


def main():

    outdir = os.path.join("tests", "data")
    metagenome = os.path.join(outdir, "records.fna")
    metagenome_nucl_orfs = os.path.join(outdir, "metagenome_nucl_orfs.fasta")
    metagenome_prot_orfs = os.path.join(outdir, "metagenome_prot_orfs.fasta")
    # coverage_reads = os.path.join(outdir, "coverage_reads.fastq")
    # coverage_sam = os.path.join(outdir, "coverage.sam")
    # coverage_bam = os.path.join(outdir, "coverage.bam")
    # coverage_bed = os.path.join(outdir, "coverage.bed")
    markers_orfs = os.path.join(outdir, "markers_orfs.faa")
    markers_scans = os.path.join(outdir, "markers_scans.tsv.gz")
    markers_filtered = os.path.join(outdir, "markers_filtered.tsv.gz")
    taxonomy_ncbi = os.path.join("autometa", "databases", "ncbi")
    taxonmy_blastp = os.path.join(outdir, "blastp.tsv.gz")
    taxonomy_orfs = os.path.join(outdir, "taxonomy_orfs.faa")
    binning_norm_kmers = os.path.join(outdir, "binning_kmers.am_clr.tsv.gz")
    binning_embedded_kmers = os.path.join(outdir, "binning_kmers.am_clr.bhsne.tsv.gz")
    binning_coverage = os.path.join(outdir, "binning_coverage.tsv.gz")
    binning_markers = os.path.join(outdir, "binning_markers.tsv.gz")
    binning_taxonomy = os.path.join(outdir, "binning_taxonomy.tsv.gz")

    test_data = TestData(
        metagenome=metagenome,
        metagenome_nucl_orfs=metagenome_nucl_orfs,
        metagenome_prot_orfs=metagenome_prot_orfs,
        markers_orfs=markers_orfs,
        markers_scans=markers_scans,
        markers_filtered=markers_filtered,
        taxonomy_ncbi=taxonomy_ncbi,
        taxonmy_blastp=taxonmy_blastp,
        taxonomy_orfs=taxonomy_orfs,
        binning_norm_kmers=binning_norm_kmers,
        binning_embedded_kmers=binning_embedded_kmers,
        binning_coverage=binning_coverage,
        binning_markers=binning_markers,
        binning_taxonomy=binning_taxonomy,
    )

    # TODO: Decrease the size of the test_data.json file...
    test_data.get_kmers()
    # COMBAK: Minimize data structures for coverage test data
    test_data.get_coverage()
    # # COMBAK: Minimize data structures for taxonomy test data
    test_data.get_taxonomy()
    test_data.get_markers()
    test_data.get_binning()

    out = os.path.join(outdir, "test_data.json")
    test_data.to_json(out=out)
    return


if __name__ == "__main__":
    main()
