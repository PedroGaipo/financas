import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, date
import plotly.express as px

# --- CONFIGURAÇÃO DA CONEXÃO ---
# No Streamlit Cloud, adicione o link da planilha em Settings > Secrets
conn = st.connection("gsheets", type=GSheetsConnection)

# --- FUNÇÕES DE DADOS (AGORA COM GOOGLE SHEETS) ---

def ler_dados(aba):
    try:
        return conn.read(worksheet=aba, ttl=0) # ttl=0 evita cache para ver dados na hora
    except:
        # Se a aba não existir, retorna um DataFrame vazio com colunas
        if aba == "transacoes":
            return pd.DataFrame(columns=['id', 'perfil', 'tipo', 'categoria', 'descrição', 'valor', 'data', 'recorrente'])
        return pd.DataFrame(columns=['nome'])

def salvar_transacao(perfil, tipo, categoria, desc, valor, data, recorrente):
    df = ler_dados("transacoes")
    # Gerar ID único (timestamp simples)
    novo_id = int(datetime.now().timestamp())
    nova_linha = pd.DataFrame([{
        "id": novo_id, "perfil": perfil, "tipo": tipo, "categoria": categoria,
        "descrição": desc, "valor": valor, "data": data, "recorrente": 1 if recorrente else 0
    }])
    df_atualizado = pd.concat([df, nova_linha], ignore_index=True)
    conn.update(worksheet="transacoes", data=df_atualizado)

def editar_transacao(id_trans, categoria, desc, valor, data, recorrente):
    df = ler_dados("transacoes")
    df.loc[df['id'] == id_trans, ['categoria', 'descrição', 'valor', 'data', 'recorrente']] = \
        [categoria, desc, valor, data, 1 if recorrente else 0]
    conn.update(worksheet="transacoes", data=df)

def excluir_transacao(id_transacao):
    df = ler_dados("transacoes")
    df = df[df['id'] != id_transacao]
    conn.update(worksheet="transacoes", data=df)

def listar_perfis():
    df = ler_dados("perfis")
    if df.empty: return ["Padrão"]
    return df['nome'].tolist()

def adicionar_perfil(nome):
    df = ler_dados("perfis")
    if nome not in df['nome'].values:
        nova_linha = pd.DataFrame([{"nome": nome}])
        df_atualizado = pd.concat([df, nova_linha], ignore_index=True)
        conn.update(worksheet="perfis", data=df_atualizado)

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

# Roda automação
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
            salvar_transacao(st.session_state['perfil_ativo'], "Despesa", cat_d, desc_d, val_d, dat_d.strftime("%Y-%m-%d"), rec_d)
            st.rerun()

with col_btn2:
    with st.popover("Nova Receita", use_container_width=True):
        cat_r = st.text_input("Categoria", key="cat_r")
        desc_r = st.text_input("Descrição", key="desc_r")
        val_r = st.number_input("Valor", min_value=0.0, key="val_r")
        dat_r = st.date_input("Data", date.today(), key="dat_r")
        rec_r = st.checkbox("Recorrente?", key="rec_r")
        if st.button("Confirmar Receita"):
            salvar_transacao(st.session_state['perfil_ativo'], "Receita", cat_r, desc_r, val_r, dat_r.strftime("%Y-%m-%d"), rec_r)
            st.rerun()

st.divider()

# --- CARREGAMENTO PARA AS ABAS ---
df_bruto = ler_dados("transacoes")
df_perfil = df_bruto[df_bruto['perfil'] == st.session_state['perfil_ativo']]

tab1, tab2, tab3 = st.tabs(["📊 Visão Geral", "📈 Gráficos", "⚙️ Configurações"])

with tab1:
    st.subheader("🔍 Filtrar Histórico")
    c_f1, c_f2, _ = st.columns([1.5, 1.5, 5])
    with c_f1: d_ini1 = st.date_input("Início", value=date(2024, 1, 1), key="t1_i")
    with c_f2: d_fim1 = st.date_input("Fim", value=date.today(), key="t1_f")

    if not df_perfil.empty:
        df_perfil['data'] = pd.to_datetime(df_perfil['data'])
        df_filtrado = df_perfil[(df_perfil['data'].dt.date >= d_ini1) & (df_perfil['data'].dt.date <= d_fim1)].copy()
        
        # Resumo
        rec_val = df_filtrado[df_filtrado['tipo'] == 'Receita']['valor'].sum()
        desp_val = df_filtrado[df_filtrado['tipo'] == 'Despesa']['valor'].sum()
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Receitas", f"R$ {rec_val:,.2f}")
        m2.metric("Despesas", f"R$ {desp_val:,.2f}")
        m3.metric("Saldo", f"R$ {rec_val - desp_val:,.2f}")
        
        # Exibição Tabelas Separadas (Receitas e Despesas)
        col_rec, col_desp = st.columns(2)
        with col_rec:
            st.write("### 🟢 Receitas")
            st.dataframe(df_filtrado[df_filtrado['tipo'] == 'Receita'], use_container_width=True, hide_index=True)
        with col_desp:
            st.write("### 🔴 Despesas")
            st.dataframe(df_filtrado[df_filtrado['tipo'] == 'Despesa'], use_container_width=True, hide_index=True)

        # Edição/Exclusão
        col_ed1, col_ed2 = st.columns(2)
        with col_ed1:
            with st.expander("📝 Editar Registro"):
                id_edit = st.number_input("ID do registro:", step=1, min_value=0)
                if id_edit in df_perfil['id'].values:
                    item = df_perfil[df_perfil['id'] == id_edit].iloc[0]
                    # Form de edição (omiti campos repetidos para brevidade, mas siga a lógica anterior)
                    if st.button("Salvar Edição"):
                        # Chamar editar_transacao(...)
                        st.rerun()
        with col_ed2:
            with st.expander("🗑️ Excluir Registro"):
                id_del = st.number_input("ID para excluir:", step=1, min_value=0, key="del_id")
                if st.button("Remover", type="primary"):
                    excluir_transacao(id_del)
                    st.rerun()

    
with tab2:
    st.subheader("📈 Análise de Gastos e Receitas")
    c_g1, c_g2, _ = st.columns([1.5, 1.5, 5])
    with c_g1: d_ini2 = st.date_input("Início", value=date(2024, 1, 1), key="t2_i")
    with c_g2: d_fim2 = st.date_input("Fim", value=date.today(), key="t2_f")
    
    if not df_bruto.empty:
        df_bruto['data'] = pd.to_datetime(df_bruto['data'])
        df_graf = df_bruto[(df_bruto['data'].dt.date >= d_ini2) & (df_bruto['data'].dt.date <= d_fim2)]
        
        if not df_graf.empty:
            # Agrupamos os dados para o gráfico
            chart_data = df_graf.groupby(['categoria', 'tipo'])['valor'].sum().reset_index()
            
            # CRIANDO O GRÁFICO COM PLOTLY
            fig = px.bar(
                chart_data, 
                x="categoria", 
                y="valor", 
                color="tipo",
                barmode="group", # Barras lado a lado
                title="Gastos e Receitas por Categoria",
                # DEFINIÇÃO DAS CORES EXATAS:
                color_discrete_map={
                    "Receita": "#2ecc71",
                    "Despesa": "#e74c3c"
                },
                labels={'valor': 'Valor (R$)', 'categoria': 'Categoria', 'tipo': 'Tipo'},
                height=600
            )
            
            # Ajustes finos de layout
            fig.update_layout(
                xaxis_title="Categorias",
                yaxis_title="Valor em Reais",
                legend_title="Legenda",
                hovermode="x unified" # Mostra os valores ao passar o mouse
            )

            # EXIBINDO O GRÁFICO
            st.plotly_chart(fig, use_container_width=False)
            
        else:
            st.warning("Sem dados no período selecionado.")
    else:
        st.info("Adicione dados para gerar os gráficos.")

with tab3:
    st.subheader("👤 Gerenciar Perfis")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        perfis = listar_perfis()
        idx = perfis.index(st.session_state['perfil_ativo']) if st.session_state['perfil_ativo'] in perfis else 0
        escolha = st.selectbox("Trocar Perfil:", perfis, index=idx)
        if st.button("Trocar"):
            st.session_state['perfil_ativo'] = escolha
            st.rerun()
    with col_p2:
        novo = st.text_input("Novo Perfil:")
        if st.button("Criar"):
            if novo:
                adicionar_perfil(novo)
                st.session_state['perfil_ativo'] = novo
                st.rerun()

