# -*- coding: utf-8 -*-
"""
Created on Fri May 12 11:55:40 2023

@author: annaj
"""

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from random import sample, seed
from sklearn.feature_selection import SelectKBest, chi2
import mrmr
import sys
from scipy.special import logsumexp
from pygad import GA


# import from own files
from UBayconstraint import UBayconstraint


class UBaymodel():
    """
    Initialization of a UBaymodel.
    
    PARAMETERS
    -----
    data: <numpy array> or <pandas dataframe>
        Dataset on which feature selection shall be performed. 
        Variable types must be numeric or integer.
    target: <numpy array> or <pandas dataframe>
        Response variable of data.
        Variable types must be numeric or integer.
    feat_names : <list>
        List holding feature names. Preferably a list of string values. 
        If empty, feature names will be generated automatically. 
        Default: ``feat_names=[]``.
    M : <int>
        Positive integer determining the number of ensemble models. Default ``M=100``.
	tt_split : <float>
        Ratio of samples used for training a single ensemble model. Default ``tt_split=0.75``.
    nr_features : <string or int>
        Number of features selected in a single ensemble. Default: ``nr_features="auto"``.
            - ``string="auto"`` : A random number between 1 and the total number of features. 
            - ``int`` : A positive integer.
    method : <list of strings>
        List of feature selectors used as ensemble feature selectors.Currently options are:
            - ``mrmr`` : minimum Redundancy maximal Relevance criterion. This method supports classification and regression tasks.
            - ``chi`` : chi square whatever
            - ``fisher`` : Fisher score (classification only)
    prior_model : <string>
        Type of prior. Default: ``prior_model="dirichlet"``. So far, "dirichlet" is the only implemented prior model type.
    weights : <list>
        A list of integers defining the prior weights of the features. If a list with only one entry is used, this value is assigned to each feature as prior weight. Default: ``weight=[1]``
    constraints: <UBayconstraint>
        A UBayconstraint object describing user-defined constraints. See description UBayconstraint. Default: ``constraints=None``
    l : <float>
        Positive float. The Lagrange parameter defining the penalization strength imposed on a feature set violating the constraints. Default: ``l=1``
    optim_method : <string>
        Optimizer. Currently only Genetic Algorithm "GA" available. Default: ``optim_metod="GA"``
    popsize : <integer>
        Positive integer for the population size in GA.
    maxiter : <integer>
        Positive integer for the maximal number of GA iterations.     
    """
    
    def __init__(self, data, target, feat_names = [], M=100, tt_split=0.75, 
                 nr_features="auto",
                 method=["mrmr"], prior_model="dirichlet", weights=[1], 
                 constraints=None, l=1, optim_method="GA", popsize=100, maxiter=100,
                 random_state=None):
        
        
        self.data = pd.DataFrame(data)
        self.nrow, self.ncol = np.shape(data)
        target = target.values if isinstance(target, pd.DataFrame) else target
        self.target = target[:,0] if len(np.shape(target)) == 2 else target # transform target to 1-d nparray
        self.M = M
        self.tt_split = tt_split
        self.method = method
        self.prior_model = prior_model
        self.l = l
        self.random_state = random_state
        self.constraints = []
        self.setWeights(weights)
        self.setOptim(optim_method, popsize, maxiter)
        
        
        if constraints is not None:
            self.setConstraints(constraints, append=True)
        
        # catch errors
        if self.data.isnull().values.any():
            sys.exit("Error: NA values not supported!")
        if len(self.data) != len(self.target):
            sys.exit("Error: number of labels must match number of data rows!") 
        if (self.M % 1 != 0) or (self.M <= 0):
            sys.exit("Error: M must be a positive integer")
        if (self.tt_split < 0) or (self.tt_split >1):
            sys.exit("Error: tt_split should not be outs")
        if (self.tt_split < 0.5) or (self.tt_split > 0.99):
            print("Warning: tt_split should not be outside [0.5,0.99]")
        if not ((isinstance(self.l, int)) or (isinstance(self.l, float))):
            sys.exit("Error: l must be a positive scalar!")
        if self.l <= 0:
            sys.exit("Error: l must be a positive scalar!")
            
            
        # binary classification or regression
        self.binary = np.array_equal(self.target, self.target.astype(bool))
    
        
        
        if len(feat_names) == 0:
            self.feat_names = ['f' + str(ind) for ind in range(self.ncol)]
        else:
            self.feat_names = feat_names
        self.data.columns = self.feat_names
        self.ensemble_matrix = pd.DataFrame(columns=self.feat_names)
        
        for i in range(self.M):
            if self.binary == True:
                train_data, _, train_labels, _ = train_test_split(self.data, self.target, 
                                                           train_size=self.tt_split, stratify=self.target, random_state=i)
                
            else:
                train_data, _, train_labels, _ = train_test_split(self.data, self.target, 
                                                           train_size=self.tt_split, random_state=i)
            # non constant columns
            nconst_cols = np.where(train_data.nunique() != 1)[0]
            self.nconst_cols = nconst_cols
            train_data = train_data.iloc[:,nconst_cols]
            self.nconst_feature_names = [self.feat_names[i] for i in nconst_cols]
            
            # number of features
            if nr_features == "auto":
                seed(self.random_state)
                self.nr_features = sample(list(np.arange(1,self.ncol)),1)[0]
            else:
                self.nr_features = nr_features
                

            if self.binary:
                train_labels = train_labels.astype(int)
            else:
                train_labels = train_labels.astype(float)
                
            for m in self.method:
                self.ensemble_fails = 0
                try:
                    if callable(m):
                        ranks = m(train_data.values, train_labels, self.nr_features)
                        ranks = [self.nconst_feature_names[i] for i in ranks]
                    elif m in ["mRMR", "mrmr"]:
                        if self.binary:
                            ranks = mrmr.mrmr_classif(pd.DataFrame(train_data.values), train_labels, 
                                                      self.nr_features, show_progress=False)
                            
                        else:
                            ranks = mrmr.mrmr_regression(pd.DataFrame(train_data.values), train_labels, 
                                                      self.nr_features, show_progress=True)
                        ranks = [self.nconst_feature_names[i] for i in ranks]
                       
                        
                    vec = pd.DataFrame(columns=self.feat_names)
                    vec.loc[0] = np.repeat(0, self.ncol)
                    vec.loc[:,ranks] = 1
                    self.ensemble_matrix = pd.concat([self.ensemble_matrix,
                                                  vec], ignore_index=False)
                except:
                    print("method not working for in this iteration...")
                    self.ensemble_fails += 1
                
        
        if np.ceil(len(self.ensemble_matrix) / len(self.method)) < np.ceil(self.M / 2):
            sys.exit("Too many ensembles could not be performed!")
        
        # structure results
        self.counts = pd.Series(np.sum(self.ensemble_matrix, axis=0))
        
        
    def setWeights(self, weights, block_list=None, block_matrix=None):
        """
        Set prior weights.
    
        PARAMETERS
        -----
        weights : <list>
            A list of integers defining the prior weights of the features. If a list with only one entry is used, this value is assigned to each feature as prior weight.
            Block assignment information for features.
        block_matrix : <np.array>
            Numpy array matrix definint the block assignment information for features. 
        """
        if (len(weights) >1) and (len(weights) != self.ncol):
            sys.exit("Error: length of prior weights does not match data matrix")
            
        
        if len(weights) == 1:
            weights = np.repeat(weights, self.ncol)
        
        if any(weights) <= 0:
            sys.exit("Error: weights must be positive")
            
        if (block_matrix is not None) or (block_list is not None):
            if block_matrix is None:
                block_matrix = np.zeros((len(block_list), self.ncol))
            for i in range(len(block_list)):
                block_matrix[i,block_list[i]] = 1
            weights = np.matmul(np.transpose(block_matrix), weights.reshape(-1,1))
            
            if np.shape(block_matrix)[0] != len(weights):
                sys.exit("Error: wrong length of weights vector: must match number of blocks, if block_matrix or block_list are provided")
            self.weights = weights
        else:
            self.weights = weights
            
        self.block_matrix = block_matrix
        
    def getWeights(self):
        """
        Get prior weights.
    
        Returns
        -----
        A numpy array with the prior weights.
        """
        return self.weights
    
    
                
    def setOptim(self, optim_method, popsize, maxiter):
        """
        Set parameters for optimization.
    
        PARAMETERS
        -----
        optim_method : <string>
            Currently only genetic algorithm ("GA") possible.
        popsize : <integer>
            Positive integer for the population size in GA.
        maxiter : <integer>
            Positive integer for the maximal number of GA iterations.     
        """
        # check if method is empty
        self.optim_method = optim_method
        self.popsize = popsize
        self.maxiter = maxiter
        
    def getOptim(self):
        """
        Get optimization parameters.
    
        Returns
        -----
        A dictionary with the optimization parameters.
        """
        return {"optim_method":self.optim_method, "popsize":self.popsize, "maxiter":self.maxiter}
        
    def setConstraints(self, constraints, append=False):
        """
        Set side oconstraints.

        PARAMETERS
        -----
        constraints: <UBayconstraint>
            A UBayconstraint object describing user-defined constraints. See description UBayconstraint.
        append : <boolean>
            - True: Append a new constraint to the list of present constraints 
            - False: Replace all present constraints with the new constraint
        """
        if constraints.get_dimensions()[1] != self.ncol:
            sys.exit("Dimensions of constraints do not match")
        
        if append:
            # check if block matrix already present
            bm_appearance = [np.array_equal(constraints.block_matrix, i.block_matrix) for i in self.constraints]
            if sum(bm_appearance) > 0:
                index = int(np.where(bm_appearance)[0])
                self.constraints[index].A = np.append(self.constraints[index].A, constraints.A, axis=0)
                self.constraints[index].b = np.append(self.constraints[index].b, constraints.b)
                self.constraints[index].rho = np.append(self.constraints[index].rho, constraints.rho)
            else:
                self.constraints = self.constraints + [constraints]
        else:
            self.constraints = [constraints]
            
    def getConstraints(self):
        """
        Get side constraints.
    
        Returns
        -----
        A list.
        """
        return self.constraints    
        
    def admissibility(self, state, log=True):
        """
        Get admissibility of a feature set.
        PARAMETERS
        -----
        state : <np.array>
            Binary 1-d array indicating which features are selected (1) and which are not selected (0).
        log : <boolean>
            Use of log-scale.
    
        Returns
        -----
        A numeric value.
        """
        adm = 1-log
        for i in self.constraints:
            if log:
                adm = adm + i.group_admissibility(state, log=log)
            else:
                adm = adm * i.group_admissibility(state, log=log)
        return adm
        
    def posteriorExpectation(self):
        """
        Posterior expectation score.
           
        Returns
        -----
        A numeric value.
        """
        post_scores = self.counts.values.astype(int) + self.weights
        post_scores = np.log(post_scores) - np.log(np.sum(post_scores))
        return post_scores
        
        
    def train(self):
        """
        Train the UBaymodel.
           
        Returns
        -----
            <pandas dataframe> with the optimal feature set and their names as index
            <list> of selected feature names
        """
        # check if any constraint present:
        if len(self.constraints) == 0:
            sys.exit("At least a max-size constraint must be present for training!")
        
        
        theta = self.posteriorExpectation()
        
        def fitness_fun(ga_instance, solution, solution_idx):
            return logsumexp(np.array(list(theta[solution==1]) + [np.log(self.l) + self.admissibility(solution)]))
        
        x_start = self.sampleInitial(post_scores = np.exp(theta), size=self.popsize)
        ga_instance = GA(num_generations = self.maxiter,
                   num_parents_mating = self.popsize,
                   fitness_func = fitness_fun,
                   initial_population = x_start,
                   gene_type=int,
                   init_range_high=1,
                   init_range_low=0,
                   random_seed=self.random_state
                   )
        
        x_optim, x_optim_fitness, _ = ga_instance.best_solution()
        
        
        return  pd.DataFrame(x_optim, index=self.feat_names), list(np.array(self.feat_names)[np.where(x_optim ==1)[0]])
        
    def sampleInitial(self, post_scores, size):
        """
        Sample an initial feature set based on a search heuristic.
           
        Returns
        -----
        A binary <numpy array> feature set.
        """
        n = len(post_scores)
        num_constraints_per_block = [const.get_dimensions()[0] for const in self.constraints]
        cum_num_constraints_per_block = np.array([0] + list(np.cumsum(num_constraints_per_block)))
        rho = np.concatenate([const.rho for const in self.constraints])
        rho = 1 / (1 + rho)
        
        def full_admissibility(state, constraint_dropout, log=True):
            
            active_constraints = np.where(constraint_dropout == 1)[0]
            res = 1-log
            
            for i in range(len(self.constraints)):
                
                active_constraints_in_block = \
                    active_constraints[np.where([np.sum(j >= cum_num_constraints_per_block) == (i+1) for j in active_constraints])[0]] - \
                    cum_num_constraints_per_block[i]
                
                if len(active_constraints_in_block) > 0:
                    constraint_new = UBayconstraint(rho=self.constraints[i].rho[active_constraints_in_block],
                                                    A=self.constraints[i].A[active_constraints_in_block,:],
                                                    b=self.constraints[i].b[active_constraints_in_block],
                                                    block_matrix=self.constraints[i].block_matrix)
                        
                    a = constraint_new.group_admissibility(state, log=log)
                    res = res + a if log else res * a
            return res
          
        
        def order_features(order):
            
            rho_mat = np.column_stack((rho, 1-rho))
            constraint_dropout = np.array([])
            for i in range(rho_mat.shape[0]):
                probs = rho_mat[i,:]
                constraint_dropout = np.append(constraint_dropout, \
                                               [np.random.choice([0,1],size=1,replace=True,p=probs)[0]])
            
            x = np.zeros(n)
            for i in range(n):
                x_new = x.copy()
                x_new[order[i]] = 1
                if full_admissibility(state=x_new, constraint_dropout=constraint_dropout,log=False) == 1:
                    x = x_new             
            return x
        
        # apply along feature_orders
        
        feature_orders = []
        seed(self.random_state) 
        for i in range((size)):
            feature_orders.append(np.random.choice(range(self.ncol), size=self.ncol, replace=False, p=post_scores))
    
        feature_orders = np.transpose(np.stack(feature_orders)) 
        x_start = np.transpose(np.apply_along_axis(order_features, 0, feature_orders))
        
        
        # always add feature set with best scores
        
        ms = []
        for i in self.constraints:
            ms_c = i.get_maxsize()
            if ms_c is not None:
                ms.append(ms_c)
                
        if (len(ms) == 1) and (ms[0] > 0):
            ms = int(ms[0])
            ms_sel = (-post_scores).argsort()[:ms]
            add_x = np.zeros(x_start.shape[1])
            add_x[ms_sel] = 1
            x_start = np.vstack([x_start, add_x])
            self.x_start = x_start
        else:
            sys.exit("No max-size constraint!")
            
        return x_start
            
        
    def evaluateFS(self, state, method="spearman", log=False):
        """
        Train the UBaymodel.
           
        Returns
        -----
        A <dictionary> with different key parameters of the selected feature set.
        """
        results = {}
        # correlation
        if np.sum(state) >1:
            c = np.abs(self.data.iloc[:,state==1].corr(method=method)).values
            average_feature_correlation = np.round((np.sum(c) - np.sum(np.diag(c))) / (np.sum(state) * (np.sum(state)-1)),3)
        else:
            c = None
            average_feature_correlation = None
        
        
        # posterior scores
        post_scores = self.posteriorExpectation()
        
        log_post = logsumexp(post_scores[state == 1]) if any(state == 1) else -np.Inf

        neg_loss = np.exp(logsumexp(np.array(list(post_scores[state==1]) + [np.log(self.l) + self.admissibility(state, log=True)]))) - \
            self.l
        if log:
            neg_loss = np.log(neg_loss)
            
        # calculate number of violated constraints
        num_violated_constraints = 0
        for constraint in self.constraints:
            num_violated_constraints +=  \
            np.sum(np.matmul(constraint.A, np.matmul(constraint.block_matrix, state)>0) > constraint.b)
            
        # calculate output metrics
        results["cardinality"] = np.sum(state)
        results["total utility"] = np.round(neg_loss,3)
        results["posterior feature utility"] = np.round(log_post, 3) if log else np.round(np.exp(log_post),3)
        results["admissibility"] = np.round(self.admissibility(state,log=log),3)
        results["number of violated constraints"] = num_violated_constraints
        results["average feature correlation"] = average_feature_correlation
        
        return results
                   
                
                    
                    
        