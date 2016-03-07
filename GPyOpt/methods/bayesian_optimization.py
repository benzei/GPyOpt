# Copyright (c) 2016, the GPyOpt Authors
# Licensed under the BSD 3-clause license (see LICENSE.txt)

import GPy
import deepgp
import numpy as np
import time
from ..acquisitions import AcquisitionEI, AcquisitionMPI, AcquisitionLCB, AcquisitionEI_MCMC, AcquisitionMPI_MCMC, AcquisitionLCB_MCMC  
from ..core.bo import BO
from ..core.task.space import Design_space, bounds_to_space
from ..core.task.objective import SingleObjective
from ..core.task.cost import CostModel
from ..util.general import samples_multidimensional_uniform, reshape, evaluate_function
from ..util.stats import initial_design
from ..models.gpmodel import GPModel, GPModel_MCMC
from ..optimization.acquisition_optimizer import AcquisitionOptimizer

import warnings
warnings.filterwarnings("ignore")

class BayesianOptimization(BO):

    def __init__(self, f, domain = None, constrains = None, cost_withGradients = None, model_type = 'GP', X = None, Y = None, 
    	initial_design_numdata = None, initial_design_type='random', acquisition_type ='EI', normalize_Y = True, 
        exact_feval = False, acquisition_optimizer_type = 'lbfgs', model_update_interval=1, verbosity=0, bath_method_type = 'LP', 
        batch_size = 1, num_cores = 1, **kwargs):

        self.verbosity              = verbosity
        self.model_update_interval  = model_update_interval
        self.kwargs = kwargs

        # --- CHOOSE design space
        if domain == None and self.kwargs.has_key('bounds'): 
            self.domain = bounds_to_space(kwargs['bounds'])
        else: 
            self.domain = domain 
        self.constrains = constrains
        self.space = Design_space(self.domain, self.constrains)

        # --- CHOOSE objective function
        self.f = f
        self.batch_size = batch_size
        self.num_cores = num_cores
        self.objective = SingleObjective(self.f, self.batch_size, self.num_cores, **kwargs)

        # --- CHOOSE the cost model
        self.cost = CostModel(cost_withGradients)

        # --- CHOOSE initial design
        self.X = X
        self.Y = Y
        self.initial_design_type  = initial_design_type
        self.initial_design_numdata = initial_design_numdata
        self._init_design_chooser()

        # --- CHOOSE the model type
        self.model_type = model_type  
        self.exact_feval = exact_feval 
        self.normalize_Y = normalize_Y      
        self.model = self._model_chooser()

        # --- CHOOSE the acquisition optimizer_type
        self.acquisition_optimizer_type = acquisition_optimizer_type
        self.acquisition_optimizer = AcquisitionOptimizer(self.space, self.acquisition_optimizer_type)  ## morre arguments may come here

        # --- CHOOSE batch method
        self.bath_method_type = bath_method_type
        self.batch_size = batch_size
        self.num_cores = num_cores

        # --- CHOOSE acquistion function
        self.acquisition_type = acquisition_type
        self.acquisition = self._acquisition_chooser()

        # -- Create optimization space
        super(BayesianOptimization ,self).__init__(	model                  = self.model, 
                									space                  = self.space, 
                									objective              = self.objective, 
                									acquisition_func       = self.acquisition, 
                									X_init                 = self.X, 
                                                    Y_init                 = self.Y,
                                                    cost                   = self.cost,
                									normalize_Y            = self.normalize_Y, 
                									model_update_interval  = self.model_update_interval)


    def _model_chooser(self):
        
        if self.kwargs.has_key('kernel'): 
            self.kernel = kwargs['kernel']
        else: 
            self.kernel = None

        if self.kwargs.has_key('noise_var'): self.noise_var = kwargs['noise_var']
        else: self.noise_var = None
            
        # --- Initilize GP model with MLE on the parameters
        if self.model_type == 'GP':
            if self.kwargs.has_key('model_optimizer_type'): self.model_optimizer_type = kwargs['model_optimizer_type'] 
            else: self.model_optimizer_type = 'lbfgs' 

            if self.kwargs.has_key('optimize_restarts'): self.optimize_restarts = kwargs['optimize_restarts']
            else: self.optimize_restarts = 5

            if self.kwargs.has_key('max_iters'): self.max_iters = kwargs['max_iters']
            else: self.max_iters = 1000 

            return GPModel(self.kernel, self.noise_var, self.exact_feval, self.normalize_Y, self.model_optimizer_type, self.max_iters, self.optimize_restarts, self.verbosity)

        # --- Initilize GP model with MCMC on the parameters
        elif self.model_type == 'GP_MCMC':
            if self.kwargs.has_key('n_samples'): kwargs['n_samples']
            else: self.n_samples = 10 

            if self.kwargs.has_key('n_burnin'): kwargs['n_burnin']
            else: self.n_burnin = 100
            
            if self.kwargs.has_key('subsample_interval'): kwargs['subsample_interval']
            else: self.subsample_interval =10
            
            if self.kwargs.has_key('step_size'): kwargs['step_size']
            else: self.step_size = 1e-1
            
            if self.kwargs.has_key('leapfrog_steps'): kwargs['leapfrog_steps']
            else: self.leapfrog_steps = 20

            return  GPModel_MCMC(self.kernel, self.noise_var, self.exact_feval, self.normalize_Y, self.n_samples, self.n_burnin, self.subsample_interval, self.step_size, self.leapfrog_steps, self.verbosity)



    def _acquisition_chooser(self):

        # --- Extract relevant parameters from the ***kwargs
        if self.kwargs.has_key('acquisition_jitter'):
            self.acquisition_jitter = kwargs['acquisition_jitter']
        else:
            self.acquisition_jitter = 0.01

        if self.kwargs.has_key('acquisition_weight'):
            self.acquisition_weight = kwargs['acquisition_weight']
        else:
            self.acquisition_weight = 2  ## TODO: implement the optimal rate (only for bandits)

        # --- Choose the acquisition
        if self.acquisition_type == None or self.acquisition_type =='EI':
            return AcquisitionEI(self.model, self.space, self.acquisition_optimizer, self.cost.cost_withGradients, self.acquisition_jitter)
        
        elif self.acquisition_type =='EI_MCMC':
            return AcquisitionEI_MCMC(self.model, self.space, self.acquisition_optimizer, self.cost.cost_withGradients, self.acquisition_jitter)        
        
        elif self.acquisition_type =='MPI':
            return AcquisitionMPI(self.model, self.space, self.acquisition_optimizer, self.cost.cost_withGradients, self.acquisition_jitter)
         
        elif self.acquisition_type =='MPI_MCMC':
            return AcquisitionMPI_MCMC(self.model, self.space, self.acquisition_optimizer, self.cost.cost_withGradients, self.acquisition_jitter)

        elif self.acquisition_type =='LCB':
            return AcquisitionLCB(self.model, self.space, self.acquisition_optimizer, self.cost.cost_withGradients, self.acquisition_weight)
        
        elif self.acquisition_type =='LCB_MCMC':
            return AcquisitionLCB_MCMC(self.model, self.space, self.acquisition_optimizer, self.cost.cost_withGradients, self.acquisition_weight)        
        
        else:
            raise Exception('Invalid acquisition selected.')


    def _init_design_chooser(self):
        if self.initial_design_numdata==None: 
            self.initial_design_numdata = 5
        else: self.initial_design_numdata = initial_design_numdata

        # Case 1:
        if self.X is None:
            self.X = initial_design(self.initial_design_type, self.space, self.initial_design_numdata)
            self.Y, _ = self.objective.evaluate(self.X)

        # Case 2
        elif self.X is not None and self.Y is None:
            self.Y, _ = self.objective.evaluate(self.X)




    
