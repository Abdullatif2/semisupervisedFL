import os
import numpy as np
import collections
import warnings
from six.moves import range
import six
import tensorflow as tf
import tensorflow_federated as tff

from tensorflow_federated.python.common_libs import py_typecheck


def get_client_data(dataset_name, mask_by, mask_ratios, sample_client_data=False):
  '''
  dataset_name -- str,          name of dataset
  mask_by -- str,             indicates if we will mask by clients or examples
  mask_ratios -- dict(float), gives mask ratios for models 
                              is of format {'supervised':0.0, 'unsupervised':0.0}
  sample_dataset -- bool,     if true, will return a small ClientData dataset
                              containing 100 clients with max 100 examples each
  '''
  print(dataset_name, mask_by, mask_ratios, sample_client_data)

  assert dataset_name in ('emnist')
  assert mask_by in ('client', 'example'), 'mask_by must be `client` or `example`'

  if dataset_name == 'emnist':
    train_set, test_set = tff.simulation.datasets.emnist.load_data()

  if sample_client_data:
    train_set = get_sample_client_data(train_set, 100, 100)
    test_set = get_sample_client_data(test_set, 100, 100)

  for s in mask_ratios:
    if mask_by == 'example':
      train_set = mask_examples(train_set, mask_ratios[s], s)
    elif mask_by == 'client':
      train_set = mask_clients(train_set, mask_ratios[s], s)

  test_set = test_set.create_tf_dataset_from_all_clients()

  return train_set, test_set


def get_sample_client_data(client_data, num_clients, num_examples):
    '''
    Generates a client dataset with maximum `num_clients` number of clients and 
    `num_examples` number of examples per client

    client_data: ClientData, client dataset
    num_clients: int,         maximum number of clients in returned dataset
    num_examples: int,        maximum number of examples per client in returned dataset
    '''
    def get_dataset(client_id):
      return client_data.create_tf_dataset_for_client(client_id).take(num_examples)

    return tff.simulation.client_data.ConcreteClientData(client_data.client_ids[:num_clients], get_dataset)


def mask_true(example, mask_type):
    '''
    Adds Boolean mask attribute, such as `is_masked_supervised`, to a 
    single example and sets to True.
    '''
    key = 'is_masked_'+mask_type
    example[key] = tf.convert_to_tensor(True)
    return example


def mask_false(example, mask_type):
    '''
    Adds Boolean mask attribute, such as `is_masked_supervised`, to a 
    single example and sets to False.
    '''
    key = 'is_masked_'+mask_type
    example[key] = tf.convert_to_tensor(False)
    return example


def mask_examples(client_data, mask_ratio, mask_type, seed=None):
    '''
    Masks mask_ratio fraction of randomly selected examples on each client.

    Args:
        client_data - ClientData object containing federated dataset
        mask_ratio - float, fraction of example labels to mask
    Returns:
        client_data - ClientData object, identical to client_data argument but 
        with additional attribute `mask` boolean for each example
    '''
    def get_example_ids_generator():
      # counts number of examples per client and returns a tuple for each client id
      # with the number of masked examples it should contain
      for client_id in client_data.client_ids:
        for i, _ in enumerate(client_data.create_tf_dataset_for_client(client_id)):
          pass
        yield (client_id, int(mask_ratio*i))
    
    client_id_to_mask_idx = {x[0]:x[1] for x in get_example_ids_generator()}

    def preprocess_fn(dataset, client_id):
        return dataset.shuffle(buffer_size=500, seed=seed).enumerate().map(lambda i, x: mask_true(x, mask_type)
                                                                                  if i < client_id_to_mask_idx[client_id]
                                                                                  else mask_false(x, mask_type))
        
    tff.python.common_libs.py_typecheck.check_callable(preprocess_fn)

    def get_dataset(client_id):
      return preprocess_fn(client_data.create_tf_dataset_for_client(client_id), client_id)

    return tff.simulation.client_data.ConcreteClientData(client_data.client_ids, get_dataset)


def mask_clients(client_data, mask_ratio, mask_type, seed=None):
    '''
    Masks mask_ratio fraction of clients uniformly randomly. If a client is 
    selected as masked, all examples it contains are treated as masked.
    
    Args:
        client_data - ClientData object containing federated dataset
        mask_ratio - float, fraction of total clients to be masked
    Returns:
        client_data - ClientData object, identical to client_data argument but 
        with additional attribute `is_masked` boolean for each example
    '''
    # get client idxs to mask
    client_ids = list(client_data.client_ids)
    np.random.shuffle(client_ids)
    num_clients = len(client_data.client_ids)
    masked_client_idxs = set(client_ids[:int(mask_ratio*num_clients)])

    def preprocess_fn(dataset, client_id):
        if client_id in masked_client_idxs:
          return dataset.map(lambda x: mask_true(x, mask_type))
        else:
          return dataset.map(lambda x: mask_false(x, mask_type))

    tff.python.common_libs.py_typecheck.check_callable(preprocess_fn)

    def get_dataset(client_id):
      return preprocess_fn(client_data.create_tf_dataset_for_client(client_id), client_id)

    return tff.simulation.client_data.ConcreteClientData(client_data.client_ids, get_dataset)


def preprocess_classifier(dataset, 
                        num_epochs, 
                        shuffle_buffer, 
                        batch_size):

  def element_fn(element):
    return (tf.reshape(element['pixels'], [-1]),
            tf.reshape(element['label'], [1]))

  return dataset.filter(lambda x: not x['is_masked_supervised'] if 'is_masked_supervised' in x else True).repeat(
      num_epochs).map(element_fn).shuffle(shuffle_buffer).batch(batch_size)


def preprocess_autoencoder(dataset,
                        num_epochs, 
                        shuffle_buffer, 
                        batch_size):

  def element_fn(element):
    return (tf.reshape(element['pixels'], [-1]),
          tf.reshape(element['pixels'], [-1]))

  return dataset.filter(lambda x: not x['is_masked_unsupervised'] if 'is_masked_unsupervised' in x else True).repeat(
      num_epochs).map(element_fn).shuffle(shuffle_buffer).batch(batch_size)


class DataLoader(object):
    def __init__(self, 
                preprocess_fn,
                num_epochs = 10, 
                shuffle_buffer = 500, 
                batch_size = 128
                ):
        self.preprocess_fn = preprocess_fn
        self.num_epochs = num_epochs
        self.shuffle_buffer = shuffle_buffer
        self.batch_size = batch_size
      
    def preprocess_dataset(self, dataset):
        '''
        Preprocesses a single tf Dataset.
        '''
        return self.preprocess_fn(dataset,
                                  self.num_epochs,
                                  self.shuffle_buffer,
                                  self.batch_size
                                  )

    def make_federated_data(self, client_data, client_ids):
        '''
        Preprocesses a federated dataset containing examples corresponding to client_ids provided.
        '''
        return [self.preprocess_dataset(client_data.create_tf_dataset_for_client(x)) for x in client_ids]

    def get_sample_batch(self, client_data):
        '''
        Generates a single batch of data from a dataset.
        '''
        preprocessed_example_dataset = self.preprocess_dataset(
                  client_data.create_tf_dataset_for_client(client_data.client_ids[0]))

        return tf.nest.map_structure(
            lambda x: x.numpy(), iter(preprocessed_example_dataset).next())