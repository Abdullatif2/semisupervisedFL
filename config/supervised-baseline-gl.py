config = {}

config['experiment'] = 'SupervisedLearning'
config['verbose'] = True

dataset = {}
dataset['dataset_name'] = 'emnist'
dataset['mask_by'] = 'example'
dataset['mask_ratios'] = {'supervised':0.0, 
                        'unsupervised':1.0}
dataset['sample_client_data'] = False # must set to False when running real experiments
config['dataset'] = dataset

# data loading
config['preprocess_fn'] = 'preprocess_classifier'
config['shuffle_buffer'] = 500
config['batch_size'] = 128
config['num_epochs'] = 1

# training
config['model_fn'] = 'ClassifierModel'
config['num_rounds'] = 40
config['num_clients_per_round'] = 64
config['learning_rate'] = 0.02

config['saved_model_fp'] = None
config['model_fp'] = 'classifier.h5'
config['evaluation_fp'] = 'classifier.json'

config['results'] = {}