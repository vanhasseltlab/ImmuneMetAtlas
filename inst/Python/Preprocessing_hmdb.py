import re
import xml.etree.cElementTree as ET
import requests
import pandas as pd
import numpy as np
import io
import zipfile
import logging
from tqdm import tqdm

class HMDB:
    """ This class chunks an xml file (zipped) into chunks, so that a DOM parser can be used
    It stores only fields by using regex of the fields given
    """
    def __init__(self, options):
        self.files = {}
        self.options = options
        self.mapping = []

    def set_variables(self, source, chunk_by, fields, exclude):
        """
        This method sets the variables needed to parse the HMDB XML file in chunks
        It primarly builds a regex expression to be searched in the file and
        sets up files so the results can be written to their respective file.
        """
        self.source = source
        self.chunk_start = "<{}".format(chunk_by)
        self.chunk_end = "</{}".format(chunk_by)
        self.regex = "|".join(["{}>".format(x) for x in fields])
        self.regex = "(" + self.chunk_start + "|" + self.chunk_end + "|" + self.regex + ")"
        self.set_files(fields, exclude)

    def set_files(self, fields, exclude):
        """
        Here, files are created that are being use to write the metadata to, except
        for all fields in 'exclude'Niet d
        """
        for field in fields:
            if field not in exclude:
                self.files[field] = open(f"{self.options['folder']}/Metabolite_{field}.csv", "w", encoding="utf-8")
                self.write(field, ["ID", field])
        logging.info(f"Created necessary files")

    def chunk(self):
        """
        This method creates a generator by yielding a ElementTree object for each chunk
        """
        with self.source.open("hmdb_metabolites.xml", "r") as f:
            next(f)
            next(f)
            data = []
            s = f.readline().decode("utf-8", "ignore")
            while s:
                data += [s] if re.search(self.regex, s) is not None else []
                if self.chunk_end in s:
                    yield ET.fromstring("".join(data))
                    data = []   
                s = f.readline().decode("utf-8", "ignore")            

    def write(self, field, vals):
        """
        This method writes the values of a given field to a file.
        """
        self.files[field].write('"' + '","'.join(vals) + '"\n')

    def close(self):
        """
        Here, all files are closed. Is used after processing the XML file.
        """
        for f in self.files.values():
            f.close()

    def get_chebi_mapping(self):
        """
        Returns a dataframe that contains a mapping between HMDB and ChEBI 
        identifiers in order to use with Uniprot
        """
        df = pd.DataFrame(self.mapping, columns = ["ID", "chebi_id"]).drop_duplicates()
        df.set_index("chebi_id", inplace=True, drop = False)
        df.to_csv(f"{self.options['folder']}/Metabolite-chebi.csv", index = False)
        return df

    def is_drug(self, chunk, terms):
        name = chunk.findtext('name')
        iupac = chunk.findtext("traditional_iupac")
        try:
            return any([
                "is only found in individuals that have used or taken" in chunk.findtext("description"),
                "Naturally occurring process" not in terms and "Drug" in terms,
                re.search(f".*({name}|{re.escape(iupac)}).*(Action|Metabolism) Pathway".lower(), "".join(terms).lower())
            ])
        except:
            return False

    
    def parse_hmdb(self): 
        """
        
        """
        logging.info("Start downloading HMDB XML")
        url = 'https://hmdb.ca/system/downloads/current/hmdb_metabolites.zip'
        r = requests.get(url, stream=True)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        count = 0
        with z.open("hmdb_metabolites.xml", "r") as source:
            self.set_variables(source = z, chunk_by = "metabolite", 
                        fields = ["accession", "chebi_id", "uniprot_id", 
                                  "class", "kegg_map_id", "super_class", "description", "traditional_iupac",
                                  "biospecimen", "cellular", "name", "pathway", "term", "kingdom"],
                        exclude = ["term", "kegg_map_id", "chebi_id", "description", "traditional_iupac"])
            with tqdm(desc = "Extracting HMDB") as pbar:
                for n, chunk in enumerate(self.chunk()):
                    terms = {x.text for x in chunk.findall("term")}
                    kingdom = str(chunk.findtext("kingdom"))
                    if ("Biological role" in terms or "Naturally occurring process" in terms) and not self.is_drug(chunk, terms) and kingdom == "Organic compounds":
                        count += self.process_metabolite(chunk)
                    pbar.update(1)
        self.close()  
        logging.info(f"Extracted {count} metabolites out of {n} from HMDB")

    
    def process_metabolite(self, chunk):
        """

        """
        accession = chunk.findtext("accession")
        
        self.write("name", [accession, chunk.findtext("name").replace('"', "'")])
        self.write("class", [accession, str(chunk.findtext("class"))])
        self.write("super_class", [accession, str(chunk.findtext("super_class"))])

        for tag in ["accession", "uniprot_id", "biospecimen", "cellular"]:
            for x in chunk.findall(tag):
                self.write(tag, [accession, x.text]) 

        chebi = chunk.findtext("chebi_id")
        if chebi is not None:
            self.mapping.append([accession, "CHEBI:" + chebi])

        chunks = chunk.findall("pathway//")
        for name, kegg in zip(chunks, chunks[1:]):
            if name.tag == "name" and kegg.tag == "kegg_map_id" and kegg.text is not None:
                self.write("pathway", [accession, name.text]) 
        return 1
