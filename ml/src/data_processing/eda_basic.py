import os
import pandas as pd

# Read Olist from external location (preserve raw)
OLIST = os.path.join(os.environ.get('USERPROFILE', ''), 'Downloads', 'olist')

def load_orders():
    p = os.path.join(OLIST, 'olist_orders_dataset.csv')
    return pd.read_csv(p)

if __name__ == '__main__':
    df = load_orders()
    print(df.shape)
    print(df.columns.tolist()[:5])
