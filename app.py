import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import plotly.express as px

# --- CONFIGURAÇÃO DA CONEXÃO ---
# No Streamlit Cloud, adicione as chaves em Settings > Secrets:
# [connections.supabase]
# url = "sua_url"
# key = "sua_anon_key"
conn = st.connection("supabase", type=SupabaseConnection)

# --- FUNÇÕES DE DADOS (SUPABASE) ---

def ler_dados(tabela):
    try:
        # ttl=0 garante que os dados sejam buscados em tempo real sem cache
        res = conn.query("*", table=tabela, ttl=0).execute()
        if res.data:
            return pd.DataFrame(res.data)
        # Retorna DF vazio com as colunas caso não haja dados
        if tabela == "transacoes":
            return pd.DataFrame(columns=['id', 'perfil', 'tipo', 'categoria', 'descrição', 'valor', 'data', 'recorrente'])
        return pd.DataFrame(columns=['nome'])
    except Exception as e:
        st.error(f"Erro ao ler dados: {e}")
        return pd.DataFrame()

def salvar_transacao(perfil, tipo, categoria, desc, valor, data, recorrente):
    data_dict = {
        "perfil": perfil,
        "tipo": tipo,
        "categoria": categoria,
        "descrição": desc,
        "valor": valor,
        "data": str(data),
        "recorrente": 1 if recorrente else 0
    }
    conn.table("transacoes").insert(data_dict).execute()

def editar_transacao(id_trans, categoria, desc, valor, data, recorrente):
    data_dict = {
        "categoria": categoria,
        "descrição": desc,
        "valor": valor,
        "data": str(data),
        "recorrente": 1 if recorrente else 0
    }
    conn.table("transacoes").update(data_dict).eq("id", id_trans).execute()

def excluir_transacao(id_transacao):
    conn.table("transacoes").delete().eq("id", id_transacao).execute()

def listar_perfis():
    df = ler_dados("perfis")
    if df.empty: return ["Padrão"]
    return df['nome'].tolist()

def adicionar_perfil(nome):
    df = ler_dados("perfis")
    if nome not in df['nome'].values:
        conn.table("perfis").insert({"nome": nome}).execute()

# --- LÓGICA DE AUTOMAÇÃO ---
def processar_recorrencias(perfil):
    df = ler_dados("transacoes")
    if df.empty: return
    
    hoje = date.today()
    inicio_mes = hoje.replace(day=1).strftime("%Y-%m-%d")
    
    # Filtra modelos recorrentes do passado
    modelos = df[(df['perfil'] == perfil) & (df['recorrente'] == 1) & (df['data'] < inicio_mes)]
    modelos = modelos.drop_duplicates(subset=['categoria', 'descrição'])

    for _, row in modelos.iterrows():
        ja_existe = df[(df['perfil'] == perfil) & (df['categoria'] == row['categoria']) & 
                       (df['descrição'] == row['descrição']) & (df['data'] >= inicio_mes)]
        if ja_existe.empty:
            salvar_transacao(perfil, row['tipo'], row['categoria'], row['descrição'], row['valor'], inicio_mes, True)

# --- INICIALIZAÇÃO DA INTERFACE ---
st.set_page_config(page_title="Gestor Financeiro Cloud", layout="wide")

if 'perfil_ativo' not in st.session_state:
    st.session_state['perfil_ativo'] = "Padrão"

# Roda automação ao carregar
processar_recorrencias(st.session_state['perfil_ativo'])

st.title(f"💰 Gestor Cloud: {st.session_state['perfil_ativo']}")

# --- BOTÕES DE LANÇAMENTO ---
col_btn1, col_btn2, _ = st.columns([1.5, 1.5, 5])
with col_btn1:
    with st.popover("Nova Despesa", use_container_width=True):
        cat_d = st.text_input("Categoria", key="cat_d")
        desc_d = st.text_input("Descrição", key="desc_d")
        val_d = st.number_input("Valor", min_value=0.0, key="val_d")
        dat_d = st.date_input("Data", date.today(), key="dat_d")
        rec_d = st.checkbox("Recorrente?", key="rec_d")
        if st.button("Confirmar Despesa"):
            salvar_transacao(st.session_state['perfil_ativo'], "Despesa", cat_d, desc_d, val_d, dat_d, rec_d)
            st.rerun()

with col_btn2:
    with st.popover("Nova Receita", use_container_width=True):
        cat_r = st.text_input("Categoria", key="cat_r")
        desc_r = st.text_input("Descrição", key="desc_r")
        val_r = st.number_input("Valor", min_value=0.0, key="val_r")
        dat_r = st.date_input("Data", date.today(), key="dat_r")
        rec_r = st.checkbox("Recorrente?", key="rec_r")
        if st.button("Confirmar Receita"):
            salvar_transacao(st.session_state['perfil_ativo'], "Receita", cat_r, desc_r, val_r, dat_r, rec_r)
            st.rerun()

st.divider()

# --- CARREGAMENTO PARA AS ABAS ---
df_bruto = ler_dados("transacoes")
df_perfil = df_bruto[df_bruto['perfil'] == st.session_state['perfil_ativo']] if not df_bruto.empty else pd.DataFrame()

tab1, tab2, tab3 = st.tabs(["📊 Visão Geral", "📈 Gráficos", "⚙️ Configurações"])

with tab1:
    st.subheader("🔍 Filtrar Histórico")
    c_f1, c_f2, _ = st.columns([1.5, 1.5, 5])
    with c_f1: d_ini1 = st.date_input("Início", value=date(2024, 1, 1), key="t1_i")
    with c_f2: d_fim1 = st.date_input("Fim", value=date.today(), key="t1_f")

    if not df_perfil.empty:
        df_perfil['data'] = pd.to_datetime(df_perfil['data'])
        df_filtrado = df_perfil[(df_perfil['data'].dt.date >= d_ini1) & (df_perfil['data'].dt.date <= d_fim1)].copy()
        
        # Métricas
        m1, m2, m3 = st.columns(3)
        rec_val = df_filtrado[df_filtrado['tipo'] == 'Receita']['valor'].sum()
        desp_val = df_filtrado[df_filtrado['tipo'] == 'Despesa']['valor'].sum()
        m1.metric("Receitas", f"R$ {rec_val:,.2f}")
        m2.metric("Despesas", f"R$ {desp_val:,.2f}")
        m3.metric("Saldo", f"R$ {rec_val - desp_val:,.2f}")
        
        # Tabelas
        col_rec, col_desp = st.columns(2)
        df_visual = df_filtrado.copy()
        df_visual['recorrente'] = df_visual['recorrente'].map({1: 'Fixo', 0: 'Variável'})
        
        with col_rec:
            st.write("### 🟢 Receitas")
            st.dataframe(df_visual[df_visual['tipo'] == 'Receita'], use_container_width=True, hide_index=True)
        with col_desp:
            st.write("### 🔴 Despesas")
            st.dataframe(df_visual[df_visual['tipo'] == 'Despesa'], use_container_width=True, hide_index=True)

        # Edição/Exclusão
        col_ed1, col_ed2 = st.columns(2)
        with col_ed1:
            with st.expander("📝 Editar Registro"):
                id_edit = st.number_input("ID do registro:", step=1, min_value=0)
                if id_edit in df_perfil['id'].values:
                    item = df_perfil[df_perfil['id'] == id_edit].iloc[0]
                    new_cat = st.text_input("Nova Categoria", value=item['categoria'])
                    new_desc = st.text_input("Nova Descrição", value=item['descrição'])
                    new_val = st.number_input("Novo Valor", value=float(item['valor']))
                    new_dat = st.date_input("Nova Data", value=pd.to_datetime(item['data']))
                    new_rec = st.checkbox("Recorrente?", value=bool(item['recorrente']))
                    if st.button("Salvar Edição"):
                        editar_transacao(id_edit, new_cat, new_desc, new_val, new_dat, new_rec)
                        st.rerun()
        with col_ed2:
            with st.expander("🗑️ Excluir Registro"):
                id_del = st.number_input("ID para excluir:", step=1, min_value=0, key="del_id")
                if st.button("Remover", type="primary"):
                    excluir_transacao(id_del)
                    st.rerun()
    else:
        st.info("Nenhum dado encontrado para este perfil.")

with tab2:
    st.subheader("📈 Gráficos")
    if not df_perfil.empty:
        chart_data = df_perfil.groupby(['categoria', 'tipo'])['valor'].sum().reset_index()
        fig = px.bar(chart_data, x="categoria", y="valor", color="tipo", 
                     barmode="group", color_discrete_map={"Receita": "#2ecc71", "Despesa": "#e74c3c"},
                     height=500)
        st.plotly_chart(fig, use_container_width=True)

with tab3:
    st.subheader("👤 Perfis")
    perfis = listar_perfis()
    escolha = st.selectbox("Trocar Perfil:", perfis, index=perfis.index(st.session_state['perfil_ativo']) if st.session_state['perfil_ativo'] in perfis else 0)
    if st.button("Mudar"):
        st.session_state['perfil_ativo'] = escolha
        st.rerun()
    
    novo_p = st.text_input("Novo Perfil:")
    if st.button("Adicionar"):
        if novo_p:
            adicionar_perfil(novo_p)
            st.session_state['perfil_ativo'] = novo_p
            st.rerun()
