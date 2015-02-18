from genestack import DataImporter, get_connection, PRIVATE, FileInitializer


connection = get_connection()  # create connection

importer = DataImporter(connection)  # create importer instance

# create experiment in home folder
experiment = importer.create_experiment(PRIVATE,
                                        name='Sample of paired-end reads from A. fumigatus WGS experiment',
                                        description='A segment of a paired-end whole genome sequencing experiment of A. fumigatus')


# create sequencing assay in experiment.
# use local files as source, files should be present in folder current working dir.
# don't remove them before initialization of your file finished.
assay = importer.create_sequencing_assay(experiment,
                                         name='Test paired-end sequencing of A. fumigatus',
                                         links=['ds1.gz', 'ds2.gz'],
                                         organism='Aspergillus fumigatus',
                                         method='genome variation profiling by high throughput sequencing')

print 'Successfully load file with accession', assay

# initialize file
initializer = FileInitializer(connection)
initializer.initialize([assay])
print 'Start initialization of', assay