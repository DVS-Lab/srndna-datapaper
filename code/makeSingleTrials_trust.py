#/bin/env python
# coding: utf-8








import os
import pandas as pd
import re


# In[42]:


task='trust'
#task='sharedreward'
bidsdir='/data/projects/srndna-datapaper/bids'
allfiles = [os.path.join(root,f) for root,dirs,files in os.walk(bidsdir) for f in files if 
            (('task-%s'%(task) in f))&(f.endswith('events.tsv'))]

# In[ ]:


for f in allfiles:

    try:
        sub=re.search('/func/sub-(.*)_task',f).group(1)
    except AttributeError:
        print("can't find 'sub-' in file: ",f)
    task=task
    try:
        run=re.search('run-(.*)_events',f).group(1)
    except AttributeError:
        print("can't find run", f)

    OutDir='/data/projects/srndna-datapaper/derivatives/fsl/EVfiles/sub-%s/SingleTrialEVs/task-%s/run%s'%(sub,task,run)
    os.makedirs(OutDir,exist_ok=True)
    df=pd.read_csv(f,sep='\t')
    df['mod']=1
    decision_phase=df[df['trial_type'].str.contains('choice')]
    decision_phase=decision_phase[['onset','duration','mod']]
    decision_phase.to_csv(OutDir+'/trialmodel-decisionphase_.tsv',
                     sep="\t",header=False,index=False)
    df=df[df['trial_type'].str.contains('outcome')]

    df['mod']=1
    df=df.drop_duplicates(subset=['onset','duration'],keep='last').reset_index(drop=True)
    df['trial']=df.index+1
    for trial in df['trial']:
        Single=df[df['trial']==trial]
        Other=df[df['trial']!=trial]
        
        Single=Single[['onset','duration','mod']]
        Other=Other[['onset','duration','mod']]

        Single.to_csv(OutDir+'/trialmodel-%s_estimage-single.tsv'%(trial),
                      sep="\t",header=False,index=False)
        Other.to_csv(OutDir+'/trialmodel-%s_estimage-other.tsv'%(trial),
                     sep="\t",header=False,index=False)
       

        


# In[53]:





# In[ ]:


