import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import plotly.express as px
import requests

def get_cdi_bcb():
    try:
        url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados?formato=json"
        response = requests.get(url)
        dados = response.json()
        ultimo = dados[-1]
        cdi_str = float(ultimo['valor'].replace(',', '.'))
        return cdi_str / 100
    except:
        return 0.1483  # Backup maio 2026

def formatar_data(data):
    if pd.isna(data):
        return ""
    if isinstance(data, (datetime, date)):
        return data.strftime("%d/%m/%Y")
    texto = str(data)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return texto


# --- BANCO DE DADOS ---
def init_db():
    conn = sqlite3.connect('financas.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS transacoes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, perfil TEXT, tipo TEXT, categoria TEXT, 
                  descrição TEXT, valor REAL, data TEXT, recorrente INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS perfis
                 (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)''')
    c.execute("INSERT OR IGNORE INTO perfis (nome) VALUES ('Padrão')")
    c.execute('''CREATE TABLE IF NOT EXISTS financiamentos
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  perfil TEXT,
                  nome TEXT,
                  descricao TEXT,
                  valor_total REAL,
                  num_parcelas INTEGER,
                  data_inicio TEXT,
                  taxa_juros REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS parcelas
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  financiamento_id INTEGER,
                  numero_parcela INTEGER,
                  data_vencimento TEXT,
                  valor REAL,
                  pago INTEGER DEFAULT 0,
                  data_pagamento TEXT,
                  FOREIGN KEY (financiamento_id) REFERENCES financiamentos(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS orcamentos
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  perfil TEXT,
                  nome TEXT,
                  descricao TEXT,
                  valor_limite REAL,
                  data_inicio TEXT,
                  data_fim TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS orcamento_itens
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  orcamento_id INTEGER,
                  nome_produto TEXT,
                  valor REAL,
                  num_parcelas INTEGER,
                  data_inicio TEXT,
                  FOREIGN KEY (orcamento_id) REFERENCES orcamentos(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS orcamento_parcelas
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  item_id INTEGER,
                  numero_parcela INTEGER,
                  data_vencimento TEXT,
                  valor REAL,
                  pago INTEGER DEFAULT 0,
                  data_pagamento TEXT,
                  FOREIGN KEY (item_id) REFERENCES orcamento_itens(id))''')
    conn.commit()
    conn.close()

def listar_perfis():
    conn = sqlite3.connect('financas.db')
    cursor = conn.cursor()
    cursor.execute("SELECT nome FROM perfis")
    perfis = [linha[0] for linha in cursor.fetchall()]
    conn.close()
    return perfis

def adicionar_perfil(nome):
    conn = sqlite3.connect('financas.db')
    try:
        conn.execute("INSERT INTO perfis (nome) VALUES (?)", (nome,))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

def salvar_transacao(perfil, tipo, categoria, desc, valor, data, recorrente):
    conn = sqlite3.connect('financas.db')
    c = conn.cursor()
    c.execute("INSERT INTO transacoes (perfil, tipo, categoria, descrição, valor, data, recorrente) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (perfil, tipo, categoria, desc, valor, data, 1 if recorrente else 0))
    conn.commit()
    conn.close()

def editar_transacao(id_trans, categoria, desc, valor, data, recorrente):
    conn = sqlite3.connect('financas.db')
    conn.execute('''UPDATE transacoes SET categoria=?, descrição=?, valor=?, data=?, recorrente=? 
                    WHERE id=?''', (categoria, desc, valor, data, 1 if recorrente else 0, id_trans))
    conn.commit()
    conn.close()

def excluir_transacao(id_transacao):
    conn = sqlite3.connect('financas.db')
    conn.execute("DELETE FROM transacoes WHERE id = ?", (id_transacao,))
    conn.commit()
    conn.close()

def resetar_banco():
    conn = sqlite3.connect('financas.db')
    c = conn.cursor()
    c.execute("DELETE FROM transacoes")
    conn.commit()
    conn.close()

def processar_recorrencias(perfil):
    conn = sqlite3.connect('financas.db')
    hoje = date.today()
    inicio_mes = hoje.replace(day=1).strftime("%Y-%m-%d")
    
    query = """
    SELECT tipo, categoria, descrição, valor, data 
    FROM transacoes 
    WHERE perfil = ? AND recorrente = 1 AND data < ?
    """
    modelos = pd.read_sql_query(query, conn, params=(perfil, inicio_mes))
    modelos = modelos.drop_duplicates(subset=['categoria', 'descrição'])
    
    for _, row in modelos.iterrows():
        # Verifica se já existe no MÊS ATUAL (não no histórico todo)
        check = conn.execute("""
            SELECT id FROM transacoes 
            WHERE perfil = ? AND categoria = ? AND descrição = ? 
            AND data = ?  -- MESMA DATA do mês atual
        """, (perfil, row['categoria'], row['descrição'], inicio_mes)).fetchone()
        
        if not check:
            salvar_transacao(perfil, row['tipo'], row['categoria'], row['descrição'], 
                           row['valor'], inicio_mes, True)
    conn.close()

# --- FINANCIAMENTOS ---
def calcular_parcela(valor_total, num_parcelas, taxa_juros):
    if taxa_juros == 0:
        return valor_total / num_parcelas
    r = taxa_juros / 100
    return (valor_total * r * (1 + r) ** num_parcelas) / ((1 + r) ** num_parcelas - 1)

def criar_financiamento(perfil, nome, descricao, valor_total, num_parcelas, data_inicio, taxa_juros):
    conn = sqlite3.connect('financas.db')
    c = conn.cursor()
    c.execute(
        "INSERT INTO financiamentos (perfil, nome, descricao, valor_total, num_parcelas, data_inicio, taxa_juros) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (perfil, nome, descricao, valor_total, num_parcelas, data_inicio, taxa_juros)
    )
    fin_id = c.lastrowid
    valor_parcela = calcular_parcela(valor_total, num_parcelas, taxa_juros)
    inicio = datetime.strptime(data_inicio, "%Y-%m-%d").date()
    for i in range(num_parcelas):
        vencimento = inicio + relativedelta(months=i)
        c.execute(
            "INSERT INTO parcelas (financiamento_id, numero_parcela, data_vencimento, valor, pago) VALUES (?, ?, ?, ?, 0)",
            (fin_id, i + 1, vencimento.strftime("%Y-%m-%d"), valor_parcela)
        )
    conn.commit()
    conn.close()

def listar_financiamentos(perfil):
    conn = sqlite3.connect('financas.db')
    fins = conn.execute(
        "SELECT id, nome, descricao, valor_total, num_parcelas, data_inicio, taxa_juros FROM financiamentos WHERE perfil = ? ORDER BY nome",
        (perfil,)
    ).fetchall()
    resultado = []
    for f in fins:
        fin_id = f[0]
        pago_count = conn.execute("SELECT COUNT(*) FROM parcelas WHERE financiamento_id = ? AND pago = 1", (fin_id,)).fetchone()[0]
        resultado.append({
            'id': fin_id, 'nome': f[1], 'descricao': f[2],
            'valor_total': f[3], 'num_parcelas': f[4],
            'data_inicio': f[5], 'taxa_juros': f[6],
            'pagas': pago_count
        })
    conn.close()
    return resultado

def obter_financiamento(fin_id):
    conn = sqlite3.connect('financas.db')
    f = conn.execute(
        "SELECT id, nome, descricao, valor_total, num_parcelas, data_inicio, taxa_juros FROM financiamentos WHERE id = ?",
        (fin_id,)
    ).fetchone()
    parcelas = pd.read_sql_query(
        "SELECT id, numero_parcela, data_vencimento, valor, pago, data_pagamento FROM parcelas WHERE financiamento_id = ? ORDER BY numero_parcela",
        conn, params=(fin_id,)
    )
    conn.close()
    return {
        'id': f[0], 'nome': f[1], 'descricao': f[2],
        'valor_total': f[3], 'num_parcelas': f[4],
        'data_inicio': f[5], 'taxa_juros': f[6],
        'parcelas': parcelas
    }

def toggle_parcela(parcela_id, pago_atual):
    conn = sqlite3.connect('financas.db')
    novo_estado = 0 if pago_atual else 1
    data_pag = date.today().strftime("%Y-%m-%d") if novo_estado == 1 else None
    conn.execute(
        "UPDATE parcelas SET pago = ?, data_pagamento = ? WHERE id = ?",
        (novo_estado, data_pag, parcela_id)
    )
    conn.commit()
    conn.close()

def excluir_financiamento(fin_id):
    conn = sqlite3.connect('financas.db')
    conn.execute("DELETE FROM parcelas WHERE financiamento_id = ?", (fin_id,))
    conn.execute("DELETE FROM financiamentos WHERE id = ?", (fin_id,))
    conn.commit()
    conn.close()

# --- ORÇAMENTOS ---
def criar_orcamento(perfil, nome, descricao, valor_limite, data_inicio, data_fim):
    conn = sqlite3.connect('financas.db')
    c = conn.cursor()
    c.execute(
        "INSERT INTO orcamentos (perfil, nome, descricao, valor_limite, data_inicio, data_fim) VALUES (?, ?, ?, ?, ?, ?)",
        (perfil, nome, descricao, valor_limite, data_inicio, data_fim)
    )
    conn.commit()
    conn.close()

def listar_orcamentos(perfil):
    conn = sqlite3.connect('financas.db')
    orcamentos = conn.execute(
        "SELECT id, nome, descricao, valor_limite, data_inicio, data_fim FROM orcamentos WHERE perfil = ? ORDER BY nome",
        (perfil,)
    ).fetchall()
    resultado = []
    for orc in orcamentos:
        resultado.append({
            'id': orc[0], 'nome': orc[1], 'descricao': orc[2],
            'valor_limite': orc[3], 'data_inicio': orc[4], 'data_fim': orc[5]
        })
    conn.close()
    return resultado

def obter_orcamento(orc_id):
    conn = sqlite3.connect('financas.db')
    orc = conn.execute(
        "SELECT id, nome, descricao, valor_limite, data_inicio, data_fim FROM orcamentos WHERE id = ?",
        (orc_id,)
    ).fetchone()
    conn.close()
    if orc:
        return {
            'id': orc[0], 'nome': orc[1], 'descricao': orc[2],
            'valor_limite': orc[3], 'data_inicio': orc[4], 'data_fim': orc[5]
        }
    return None

def excluir_orcamento(orc_id):
    conn = sqlite3.connect('financas.db')
    conn.execute("DELETE FROM orcamentos WHERE id = ?", (orc_id,))
    conn.commit()
    conn.close()

def atualizar_orcamento(orc_id, nome, descricao, valor_limite, data_inicio, data_fim):
    conn = sqlite3.connect('financas.db')
    conn.execute(
        "UPDATE orcamentos SET nome = ?, descricao = ?, valor_limite = ?, data_inicio = ?, data_fim = ? WHERE id = ?",
        (nome, descricao, valor_limite, data_inicio, data_fim, orc_id)
    )
    conn.commit()
    conn.close()

# --- ITEMS E PARCELAS DE ORÇAMENTOS ---
def criar_item_orcamento(orcamento_id, nome_produto, valor, num_parcelas, data_inicio):
    conn = sqlite3.connect('financas.db')
    c = conn.cursor()
    c.execute(
        "INSERT INTO orcamento_itens (orcamento_id, nome_produto, valor, num_parcelas, data_inicio) VALUES (?, ?, ?, ?, ?)",
        (orcamento_id, nome_produto, valor, num_parcelas, data_inicio)
    )
    item_id = c.lastrowid
    valor_parcela = valor / num_parcelas
    inicio = datetime.strptime(data_inicio, "%Y-%m-%d").date()
    for i in range(num_parcelas):
        vencimento = inicio + relativedelta(months=i)
        c.execute(
            "INSERT INTO orcamento_parcelas (item_id, numero_parcela, data_vencimento, valor, pago) VALUES (?, ?, ?, ?, 0)",
            (item_id, i + 1, vencimento.strftime("%Y-%m-%d"), valor_parcela)
        )
    conn.commit()
    conn.close()

def listar_itens_orcamento(orcamento_id):
    conn = sqlite3.connect('financas.db')
    itens = conn.execute(
        "SELECT id, nome_produto, valor, num_parcelas, data_inicio FROM orcamento_itens WHERE orcamento_id = ? ORDER BY nome_produto",
        (orcamento_id,)
    ).fetchall()
    resultado = []
    for item in itens:
        pago_count = conn.execute("SELECT COUNT(*) FROM orcamento_parcelas WHERE item_id = ? AND pago = 1", (item[0],)).fetchone()[0]
        resultado.append({
            'id': item[0], 'nome_produto': item[1], 'valor': item[2],
            'num_parcelas': item[3], 'data_inicio': item[4], 'pagas': pago_count
        })
    conn.close()
    return resultado

def obter_item_orcamento(item_id):
    conn = sqlite3.connect('financas.db')
    item = conn.execute(
        "SELECT id, nome_produto, valor, num_parcelas, data_inicio FROM orcamento_itens WHERE id = ?",
        (item_id,)
    ).fetchone()
    parcelas = pd.read_sql_query(
        "SELECT id, numero_parcela, data_vencimento, valor, pago, data_pagamento FROM orcamento_parcelas WHERE item_id = ? ORDER BY numero_parcela",
        conn, params=(item_id,)
    )
    conn.close()
    if item:
        return {
            'id': item[0], 'nome_produto': item[1], 'valor': item[2],
            'num_parcelas': item[3], 'data_inicio': item[4], 'parcelas': parcelas
        }
    return None

def toggle_parcela_orcamento(parcela_id, pago_atual):
    conn = sqlite3.connect('financas.db')
    novo_estado = 0 if pago_atual else 1
    data_pag = date.today().strftime("%Y-%m-%d") if novo_estado == 1 else None
    conn.execute(
        "UPDATE orcamento_parcelas SET pago = ?, data_pagamento = ? WHERE id = ?",
        (novo_estado, data_pag, parcela_id)
    )
    conn.commit()
    conn.close()

def excluir_item_orcamento(item_id):
    conn = sqlite3.connect('financas.db')
    conn.execute("DELETE FROM orcamento_parcelas WHERE item_id = ?", (item_id,))
    conn.execute("DELETE FROM orcamento_itens WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()

# --- INICIALIZAÇÃO ---
st.set_page_config(page_title="Gestor Financeiro", layout="wide")
init_db()

if 'perfil_ativo' not in st.session_state:
    st.session_state['perfil_ativo'] = "Padrão"

processar_recorrencias(st.session_state['perfil_ativo'])

st.title(f"💰 Gestor Financeiro: {st.session_state['perfil_ativo']}")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📊 Visão Geral", "📈 Gráficos", "💸 Financiamentos", "💹 Investimentos", "💳 Orçamentos", "⚙️ Configurações"])

conn = sqlite3.connect('financas.db')
df_bruto = pd.read_sql_query("SELECT * FROM transacoes WHERE perfil = ?", conn, params=(st.session_state['perfil_ativo'],))
conn.close()

# ===================== TAB 1 — VISÃO GERAL =====================
with tab1:
    st.subheader("🔍 Filtrar Histórico")
    c_f1, c_f2, _ = st.columns([1.5, 1.5, 5])
    with c_f1:
        d_ini1 = st.date_input("Início", value=date(2026, 1, 1), key="t1_i")
    with c_f2:
        d_fim1 = st.date_input("Fim", value=date.today(), key="t1_f")    

    if not df_bruto.empty:
        df_bruto['data'] = pd.to_datetime(df_bruto['data'])
        df_filtrado = df_bruto[(df_bruto['data'].dt.date >= d_ini1) & (df_bruto['data'].dt.date <= d_fim1)].copy()

        receitas_val = df_filtrado[df_filtrado['tipo'] == 'Receita']['valor'].sum()
        despesas_val = df_filtrado[df_filtrado['tipo'] == 'Despesa']['valor'].sum()
        saldo_val = receitas_val - despesas_val

        m1, m2, m3 = st.columns(3)
        m1.metric("Receitas no Período", f"R$ {receitas_val:,.2f}")
        m2.metric("Despesas no Período", f"R$ {despesas_val:,.2f}")
        m3.metric("Saldo no Período", f"R$ {saldo_val:,.2f}")
        st.divider()

        df_exibicao = df_filtrado.copy()
        df_exibicao['recorrente'] = df_exibicao['recorrente'].map({1: 'Fixo', 0: 'Variável'})
        df_exibicao['data_sort'] = df_exibicao['data']
        df_exibicao['data'] = df_exibicao['data'].apply(formatar_data)

        # --- BOTÕES DE LANÇAMENTO ---
        col_btn1, col_btn2, _ = st.columns([1.5, 1.5, 5])
        with col_btn1:
            with st.popover("Nova Receita", use_container_width=True):
                cat_r = st.text_input("Categoria", key="cat_r")
                desc_r = st.text_input("Descrição", key="desc_r")
                val_r = st.number_input("Valor", min_value=0.0, key="val_r")
                dat_r = st.date_input("Data", date.today(), key="dat_r")
                rec_r = st.checkbox("Recorrente?", key="rec_r")
                if st.button("Confirmar Receita"):
                    salvar_transacao(st.session_state['perfil_ativo'], "Receita", cat_r, desc_r, val_r, dat_r.strftime("%Y-%m-%d"), rec_r)
                    st.rerun()

        with col_btn2:
            with st.popover("Nova Despesa", use_container_width=True):
                cat_d = st.text_input("Categoria", key="cat_d")
                desc_d = st.text_input("Descrição", key="desc_d")
                val_d = st.number_input("Valor", min_value=0.01, key="val_d")
                dat_d = st.date_input("Data", date.today(), key="dat_d")
                rec_d = st.checkbox("Recorrente?", key="rec_d")
                if st.button("Confirmar Despesa") and cat_d.strip() and val_d > 0:
                    salvar_transacao(st.session_state['perfil_ativo'], "Despesa", cat_d, desc_d, val_d, 
                                dat_d.strftime("%Y-%m-%d"), rec_d)
                    st.rerun()

        def formatar_moeda(valor):
            return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        col_tab_receita, col_tab_despesa = st.columns(2)
        with col_tab_receita:
            st.write("### 🟢 Receitas")
            df_rec = df_exibicao[df_exibicao['tipo'] == 'Receita'][['categoria', 'descrição', 'valor', 'data', 'data_sort', 'id']]
            if not df_rec.empty:
                df_rec['valor'] = df_rec['valor'].apply(formatar_moeda)
                df_rec = df_rec.sort_values(by='data_sort', ascending=False).drop(columns='data_sort')
                st.dataframe(df_rec, use_container_width=True, hide_index=True)
            else:
                st.caption("Sem receitas neste período.")

        with col_tab_despesa:
            st.write("### 🔴 Despesas")
            df_desp = df_exibicao[df_exibicao['tipo'] == 'Despesa'][['categoria', 'descrição', 'valor', 'data', 'data_sort', 'id']]
            if not df_desp.empty:
                df_desp['valor'] = df_desp['valor'].apply(formatar_moeda)
                df_desp = df_desp.sort_values(by='data_sort', ascending=False).drop(columns='data_sort')
                st.dataframe(df_desp, use_container_width=True, hide_index=True)
            else:
                st.caption("Sem despesas neste período.")

        st.divider()
        col_ed1, col_ed2 = st.columns(2)
        with col_ed1:
            with st.expander("📝 Editar Registro"):
                id_edit = st.number_input("ID para editar:", step=1, min_value=0)
                if id_edit in df_bruto['id'].values:
                    item = df_bruto[df_bruto['id'] == id_edit].iloc[0]
                    new_cat = st.text_input("Nova Categoria", value=item['categoria'])
                    new_desc = st.text_input("Nova Descrição", value=item['descrição'])
                    new_val = st.number_input("Novo Valor", value=float(item['valor']))
                    new_dat = st.date_input("Nova Data", value=item['data'].to_pydatetime())
                    new_rec = st.checkbox("Recorrente?", value=bool(item['recorrente']))
                    if st.button("Salvar Alterações"):
                        editar_transacao(id_edit, new_cat, new_desc, new_val, new_dat.strftime("%Y-%m-%d"), new_rec)
                        st.success("Alterado!")
                        st.rerun()
                else:
                    st.caption("Insira um ID válido da tabela acima.")
        with col_ed2:
            with st.expander("🗑️ Excluir Registro"):
                id_del = st.number_input("ID para excluir:", step=1, min_value=0)
                if st.button("Remover", type="primary"):
                    excluir_transacao(id_del)
                    st.rerun()
    else:
        st.info("Nenhum dado.")

# ===================== TAB 2 — GRÁFICOS =====================
with tab2:
    st.subheader("📈 Análise de Gastos e Receitas")
    c_g1, c_g2, _ = st.columns([1.5, 1.5, 5])
    with c_g1:
        d_ini2 = st.date_input("Início", value=date(2024, 1, 1), key="t2_i")
    with c_g2:
        d_fim2 = st.date_input("Fim", value=date.today(), key="t2_f")

    if not df_bruto.empty:
        df_bruto['data'] = pd.to_datetime(df_bruto['data'])
        df_graf = df_bruto[(df_bruto['data'].dt.date >= d_ini2) & (df_bruto['data'].dt.date <= d_fim2)]
        if not df_graf.empty:
            chart_data = df_graf.groupby(['categoria', 'tipo'])['valor'].sum().reset_index()
            fig = px.bar(
                chart_data, x="categoria", y="valor", color="tipo", barmode="group",
                title="Gastos e Receitas por Categoria",
                color_discrete_map={"Receita": "#2ecc71", "Despesa": "#e74c3c"},
                labels={'valor': 'Valor (R$)', 'categoria': 'Categoria', 'tipo': 'Tipo'},
                height=600
            )
            fig.update_layout(xaxis_title="Categorias", yaxis_title="Valor em Reais",
                              legend_title="Legenda", hovermode="x unified")
            st.plotly_chart(fig, use_container_width=False)
        else:
            st.warning("Sem dados no período selecionado.")
    else:
        st.info("Adicione dados para gerar os gráficos.")

# ===================== TAB 3 — FINANCIAMENTOS =====================
with tab3:
    st.subheader("💸 Financiamentos")
    perfil = st.session_state['perfil_ativo']

    def fmt(valor):
        return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    with st.expander("Cadastrar novo financiamento", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            f_nome = st.text_input("Nome do financiamento", key="f_nome", placeholder="Ex: Carro, Apartamento...")
            f_desc = st.text_input("Descrição (opcional)", key="f_desc")
            f_valor = st.number_input("Valor total (R$)", min_value=0.01, step=100.0, key="f_valor")
        with c2:
            f_parcelas = st.number_input("Número de parcelas", min_value=1, step=1, value=12, key="f_parcelas")
            f_inicio = st.date_input("Data da 1ª parcela", value=date.today().replace(day=1), key="f_inicio")
            f_taxa = st.number_input("Taxa de juros mensal (%)", min_value=0.0, step=0.01, value=0.0,
                                     help="Digite 0 para parcelamento sem juros", key="f_taxa")

        if f_valor > 0 and f_parcelas > 0:
            parcela_preview = calcular_parcela(f_valor, int(f_parcelas), f_taxa)
            st.info(f"💡 Parcela mensal estimada: **{fmt(parcela_preview)}** × {int(f_parcelas)} meses")

        if st.button("✅ Criar Financiamento", type="secondary"):
            if not f_nome.strip():
                st.error("Informe o nome do financiamento.")
            elif f_valor <= 0:
                st.error("Informe um valor válido.")
            else:
                criar_financiamento(perfil, f_nome.strip(), f_desc.strip(), f_valor,
                                    int(f_parcelas), f_inicio.strftime("%Y-%m-%d"), f_taxa)
                st.success(f"Financiamento '{f_nome}' criado com {int(f_parcelas)} parcelas!")
                st.rerun()

    st.divider()

    financiamentos = listar_financiamentos(perfil)

    if not financiamentos:
        st.info("Nenhum financiamento cadastrado. Use o formulário acima para adicionar.")
    else:
        opcoes = {f['nome']: f['id'] for f in financiamentos}
        escolhido_nome = st.selectbox("Selecione um financiamento:", list(opcoes.keys()), key="f_select")
        fin_id = opcoes[escolhido_nome]
        fin = obter_financiamento(fin_id)
        df_parc = fin['parcelas']

        total_pagas = int(df_parc['pago'].sum())
        total_parcelas = fin['num_parcelas']
        valor_parcela = calcular_parcela(fin['valor_total'], total_parcelas, fin['taxa_juros'])
        restante = (total_parcelas - total_pagas) * valor_parcela

        st.markdown(f"### {fin['nome']}")
        if fin['descricao']:
            st.caption(fin['descricao'])

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Valor Total", fmt(fin['valor_total']))
        m2.metric("Parcela Mensal", fmt(valor_parcela))
        m3.metric("Parcelas Pagas", f"{total_pagas} / {total_parcelas}")
        m4.metric("Valor Restante", fmt(restante))

        progresso = total_pagas / total_parcelas if total_parcelas > 0 else 0
        st.progress(progresso, text=f"{progresso*100:.1f}% concluído")

        st.divider()
        st.markdown("#### Parcelas")

        col_filtro, _ = st.columns([1, 3])
        with col_filtro:
            filtro = st.selectbox("Exibir:", ["Todas", "Pendentes", "Pagas"], key="f_filtro")

        df_exib = df_parc.copy()
        if filtro == "Pendentes":
            df_exib = df_exib[df_exib['pago'] == 0]
        elif filtro == "Pagas":
            df_exib = df_exib[df_exib['pago'] == 1]

        for _, row in df_exib.iterrows():
            pago = bool(row['pago'])
            col_n, col_venc, col_val, col_status, col_btn = st.columns([0.5, 1.5, 1.5, 1.5, 1.5])
            with col_n:
                st.write(f"**#{int(row['numero_parcela'])}**")
            with col_venc:
                st.write(formatar_data(row['data_vencimento']))
            with col_val:
                st.write(fmt(row['valor']))
            with col_status:
                if pago:
                    if row['data_pagamento']:
                        st.success(f"✅ Paga em {formatar_data(row['data_pagamento'])}")
                    else:
                        st.success("✅ Paga")
                else:
                    st.warning("⏳ Pendente")
            with col_btn:
                label = "Desmarcar" if pago else "Marcar Paga"
                btn_type = "secondary" if pago else "primary"
                if st.button(label, key=f"toggle_{row['id']}", type=btn_type):
                    toggle_parcela(int(row['id']), pago)
                    st.rerun()

        st.divider()
        with st.expander("🗑️ Excluir este financiamento"):
            st.warning(f"Isso irá remover **{fin['nome']}** e todas as suas {total_parcelas} parcelas permanentemente.")
            if st.button("Confirmar exclusão", type="primary", key="excluir_fin"):
                excluir_financiamento(fin_id)
                st.success("Financiamento excluído.")
                st.rerun()

# ===================== TAB 4 — INVESTIMENTOS ====================
with tab4:
    st.header("💹 Investimentos")

    # Novo Investimento
    with st.expander("Novo Investimento", expanded=False):
        col_inv1, col_inv2 = st.columns(2)
        with col_inv1:
            cat_inv = st.text_input("Categoria", key="cat_inv", placeholder="Ex: CDB, Ações...")
            desc_inv = st.text_input("Descrição", key="desc_inv", placeholder="Ex: Investimento mensal")
            val_inv = st.number_input("Valor", min_value=0.01, key="val_inv")
        with col_inv2:
            dat_inv = st.date_input("Data", date.today(), key="dat_inv")
            rec_inv = st.checkbox("Recorrente?", key="rec_inv")
        if st.button("Confirmar Investimento", key="btn_inv"):
            if cat_inv.strip() and val_inv > 0:
                salvar_transacao(st.session_state['perfil_ativo'], "Investimento", cat_inv, desc_inv, val_inv, 
                               dat_inv.strftime("%Y-%m-%d"), rec_inv)
                st.success("Investimento adicionado!")
                st.rerun()
    
    somabruto = df_bruto[df_bruto['tipo'] == 'Investimento']['valor'].sum()

    # IR Regressivo
    if dat_inv <= date.today() - relativedelta(months=6): ir_aliquota = 0.225
    elif dat_inv <= date.today() - relativedelta(months=12): ir_aliquota = 0.20
    elif dat_inv <= date.today() - relativedelta(months=24): ir_aliquota = 0.175
    else: ir_aliquota = 0.15
    ir_devido = somabruto * ir_aliquota
    saldo_liquido = somabruto - ir_devido

    # Métricas
    col_res1, col_res2, col_res3 = st.columns(3)
    col_res1.metric("💵 Bruto Agora", f"R$ {somabruto:,.2f}")
    col_res2.metric("💸 IR", f"{ir_aliquota*100:.0f}% | R$ {ir_devido:,.2f}")
    col_res3.metric("💰 Líquido", f"R$ {saldo_liquido:,.2f}")

    st.divider()
# Histórico de Investimentos
    st.subheader("📈 Histórico de Investimentos")
    c_inv1, c_inv2, _ = st.columns([1.5, 1.5, 5])
    with c_inv1:
        d_ini_inv = st.date_input("Início", value=date(2024, 1, 1), key="inv_i")
    with c_inv2:
        d_fim_inv = st.date_input("Fim", value=date.today(), key="inv_f")
    
    if not df_bruto.empty:
        df_bruto['data'] = pd.to_datetime(df_bruto['data'])
        df_inv_filtrado = df_bruto[(df_bruto['data'].dt.date >= d_ini_inv) & (df_bruto['data'].dt.date <= d_fim_inv) & (df_bruto['tipo'] == 'Investimento')].copy()
        
        if not df_inv_filtrado.empty:
            df_inv_exibicao = df_inv_filtrado.copy()
            df_inv_exibicao['recorrente'] = df_inv_exibicao['recorrente'].map({1: 'Fixo', 0: 'Variável'})
            df_inv_exibicao['data_sort'] = df_inv_exibicao['data']
            df_inv_exibicao['data'] = df_inv_exibicao['data'].apply(formatar_data)
            
            def formatar_moeda(valor):
                return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            
            df_inv = df_inv_exibicao[['categoria', 'descrição', 'valor', 'data', 'recorrente', 'data_sort', 'id']]
            df_inv['valor'] = df_inv['valor'].apply(formatar_moeda)
            df_inv = df_inv.sort_values(by='data_sort', ascending=False).drop(columns='data_sort')
            st.dataframe(df_inv, use_container_width=True, hide_index=True)
        else:
            st.caption("Sem investimentos neste período.")
    
    st.divider()
    col_ed_inv1, col_ed_inv2 = st.columns(2)
    with col_ed_inv1:
        with st.expander("📝 Editar Investimento"):
            id_edit_inv = st.number_input("ID para editar:", step=1, min_value=0, key="edit_inv")
            if id_edit_inv in df_bruto['id'].values:
                item = df_bruto[df_bruto['id'] == id_edit_inv].iloc[0]
                if item['tipo'] == 'Investimento':
                    new_cat_inv = st.text_input("Nova Categoria", value=item['categoria'], key="new_cat_inv")
                    new_desc_inv = st.text_input("Nova Descrição", value=item['descrição'], key="new_desc_inv")
                    new_val_inv = st.number_input("Novo Valor", value=float(item['valor']), key="new_val_inv")
                    new_dat_inv = st.date_input("Nova Data", value=item['data'].to_pydatetime(), key="new_dat_inv")
                    new_rec_inv = st.checkbox("Recorrente?", value=bool(item['recorrente']), key="new_rec_inv")
                    if st.button("Salvar Alterações", key="save_inv"):
                        editar_transacao(id_edit_inv, new_cat_inv, new_desc_inv, new_val_inv, new_dat_inv.strftime("%Y-%m-%d"), new_rec_inv)
                        st.success("Alterado!")
                        st.rerun()
                else:
                    st.caption("Este ID não é de um investimento.")
            else:
                st.caption("Insira um ID válido da tabela acima.")
    with col_ed_inv2:
        with st.expander("🗑️ Excluir Investimento"):
            id_del_inv = st.number_input("ID para excluir:", step=1, min_value=0, key="del_inv")
            if st.button("Remover", type="primary", key="rem_inv"):
                excluir_transacao(id_del_inv)
                st.rerun()

   # ✅ CDI AUTO BCB
    cdi_real = get_cdi_bcb()
    col_cdi1, col_cdi2 = st.columns(2)
    with col_cdi1:
        st.session_state.cdi_anual = st.metric("🟢 CDI Hoje", f"{cdi_real*100:.2f}% a.a.", "🔄 BCB")
    with col_cdi2:
        st.caption(f"**Atualizado**: {date.today().strftime('%d/%m/%Y')} | API Banco Central")
    
    st.divider()
    
    # Seu input manual (backup)
    cdi_manual = st.number_input(
        "🔧 CDI Manual (%)", 
        value=cdi_real*100, step=0.01, format="%.2f"
    ) / 100
    
    # Usa cdi_manual nos cálculos abaixo...
    cdi_mensal = (1 + cdi_manual)**(1/12) - 1  

    
    # Calculadora Principal
    st.subheader("🧮 Simulador de Investimentos")
    col_calc1, col_calc2 = st.columns(2)
    
    with col_calc1:
        valor_inicial = st.number_input("💰 Valor Inicial", min_value=0.01, 
                                       value=0.01, step=100.0, format="%.2f")
        aportes_mensais = st.number_input("📈 Aporte Mensal", min_value=0.0, 
                                         value=500.0, step=100.0, format="%.2f")
        meses = st.number_input("📅 Período (meses)", min_value=1, max_value=120, 
                               value=12, step=1)
        percentual_cdi = st.number_input("✳% do CDI", 
                                        min_value=0, max_value=200, 
                                        value=100, step=5)
    
    # Cálculos
    taxa_mensal = cdi_mensal * (percentual_cdi / 100)
    
    # Simulação
    saldo = valor_inicial
    saldos = [valor_inicial]
    for m in range(meses):
        saldo += aportes_mensais
        saldo *= (1 + taxa_mensal)
        saldos.append(saldo)
    
    rendimento_bruto = saldo - valor_inicial - (aportes_mensais * meses)
    
    # IR Regressivo
    if meses <= 6: ir_aliquota = 0.225
    elif meses <= 12: ir_aliquota = 0.20
    elif meses <= 24: ir_aliquota = 0.175
    else: ir_aliquota = 0.15
    
    ir_devido = rendimento_bruto * ir_aliquota
    saldo_liquido = saldo - ir_devido
    
    # Métricas Simulador
    col_res1, col_res2, col_res3 = st.columns(3)
    col_res1.metric("💵 Bruto Final", f"R$ {saldo:,.2f}")
    col_res2.metric("💸 IR", f"{ir_aliquota*100:.0f}% | R$ {ir_devido:,.2f}")
    col_res3.metric("💰 Líquido", f"R$ {saldo_liquido:,.2f}")
    
    # Gráfico
    fig_inv = px.line(x=list(range(meses+1)), y=saldos, 
                     title=f"📊 Evolução ({percentual_cdi}% CDI)",
                     labels={'x': 'Meses', 'y': 'Saldo (R$)'})
    fig_inv.update_traces(line_color='#2ecc71', line_width=3)
    st.plotly_chart(fig_inv, use_container_width=True)
    
    st.divider()
    
    # Comparativo
    st.subheader("📋 Teste Diferentes % CDI")
    rentabilidades = [90, 95, 100, 105, 110, 120]
    dados_tabela = []
    for perc in rentabilidades:
        taxa_m = cdi_mensal * (perc / 100)
        final = valor_inicial * ((1 + taxa_m) ** meses)
        liquido = final - (final - valor_inicial) * ir_aliquota
        dados_tabela.append({
            '% CDI': f'{perc}%',
            'Bruto': f"R$ {final:,.0f}",
            'Líquido': f"R$ {liquido:,.0f}"
        })
    
    df_comp = pd.DataFrame(dados_tabela)
    st.dataframe(df_comp, use_container_width=True)
    
    # Dicas
    st.subheader("💡 Dicas do App")
    col_tip1, col_tip2 = st.columns(2)
    with col_tip1:
        st.info("✅ **CDB/LCI/LCA 100% CDI**: Mais seguros")
        st.info("🔥 **FIIs**: Renda passiva mensal")
    with col_tip2:
        st.warning("⚠️ **IR 22,5%** até 6 meses")
        st.success("🚀 **>24 meses = 15% IR**")
    
    # Rentabilidade Anual Equivalente
    st.caption(f"**Taxa Mensal Equivalente**: {taxa_mensal*100:.2f}%")
    
    st.divider()
    

# ===================== TAB 5 — ORÇAMENTOS =====================
with tab5:
    st.header("💳 Orçamentos")
    perfil = st.session_state['perfil_ativo']

    def fmt(valor):
        return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    with st.expander("Cadastrar novo orçamento", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            orc_nome = st.text_input("Nome do orçamento", key="orc_nome", placeholder="Ex: Orçamento do PC, Eletrônicos para sala...")
            orc_desc = st.text_input("Descrição (opcional)", key="orc_desc")
            orc_valor = st.number_input("Valor Limite", min_value=0.01, step=100.0, key="orc_valor")
        with col2:
            orc_inicio = st.date_input("Data Início", value=date.today().replace(day=1), key="orc_inicio")
            orc_fim = st.date_input("Data Fim (opcional)", value=date.today(), key="orc_fim")

        if st.button("✅ Criar Orçamento", type="secondary"):
            if not orc_nome.strip():
                st.error("Informe o nome do orçamento.")
            elif orc_valor <= 0:
                st.error("Informe um valor válido.")
            else:
                criar_orcamento(perfil, orc_nome.strip(), orc_desc.strip(), orc_valor,
                              orc_inicio.strftime("%Y-%m-%d"), orc_fim.strftime("%Y-%m-%d"))
                st.success(f"Orçamento '{orc_nome}' criado com limite de {fmt(orc_valor)}!")
                st.rerun()

    st.divider()

    # Listar e selecionar orçamento
    orcamentos = listar_orcamentos(perfil)

    if not orcamentos:
        st.info("Nenhum orçamento cadastrado. Use o formulário acima para adicionar.")
    else:
        opcoes = {orc['nome']: orc['id'] for orc in orcamentos}
        escolhido_nome = st.selectbox("Selecione um orçamento:", list(opcoes.keys()), key="orc_select")
        orc_id = opcoes[escolhido_nome]
        orc = obter_orcamento(orc_id)

        # Calcular gastos no período do orçamento
        if not df_bruto.empty:
            df_bruto['data'] = pd.to_datetime(df_bruto['data'])
            data_inicio = datetime.strptime(orc['data_inicio'], "%Y-%m-%d").date()
            data_fim = datetime.strptime(orc['data_fim'], "%Y-%m-%d").date()
            
            df_orc_periodo = df_bruto[(df_bruto['data'].dt.date >= data_inicio) & 
                                      (df_bruto['data'].dt.date <= data_fim) & 
                                      (df_bruto['tipo'] == 'Despesa') &
                                      (df_bruto['perfil'] == perfil)].copy()
            
            gasto_total = df_orc_periodo['valor'].sum()
        else:
            gasto_total = 0.0

        st.markdown(f"### {orc['nome']}")
        if orc['descricao']:
            st.caption(orc['descricao'])

        # Métricas
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("💰 Limite", fmt(orc['valor_limite']))
        m2.metric("💸 Gastos no período", fmt(gasto_total))
        m3.metric("📊 Restante", fmt(orc['valor_limite'] - gasto_total))
        m4.metric("📅 Período", f"{formatar_data(orc['data_inicio'])} até {formatar_data(orc['data_fim'])}")

        # Barra de progresso
        progresso = gasto_total / orc['valor_limite'] if orc['valor_limite'] > 0 else 0
        if progresso > 1:
            st.warning(f"⚠️ Orçamento excedido em {fmt(gasto_total - orc['valor_limite'])}!", icon="⚠️")
            st.progress(1.0, text=f"Excedido: {progresso*100:.1f}%")
        else:
            st.progress(progresso, text=f"{progresso*100:.1f}% utilizado")

        st.divider()
        
        # Seção de Items/Produtos do Orçamento
        st.subheader("📦 Produtos no Orçamento")
        
        # Adicionar novo item
        with st.expander("Adicionar Produto", expanded=False):
            col_item1, col_item2 = st.columns(2)
            with col_item1:
                item_nome = st.text_input("Nome do Produto", key="item_nome", placeholder="Ex: Monitor, Teclado...")
                item_valor = st.number_input("Valor", min_value=0.01, step=10.0, key="item_valor")
            with col_item2:
                item_parcelas = st.number_input("Número de Parcelas", min_value=1, step=1, value=1, key="item_parcelas")
                item_data = st.date_input("Data Inicial", value=datetime.strptime(orc['data_inicio'], "%Y-%m-%d").date(), key="item_data")
            
            if st.button("➕ Adicionar Produto", key="btn_add_item"):
                if item_nome.strip() and item_valor > 0:
                    criar_item_orcamento(orc_id, item_nome.strip(), item_valor, int(item_parcelas), item_data.strftime("%Y-%m-%d"))
                    st.success(f"Produto '{item_nome}' adicionado!")
                    st.rerun()
                else:
                    st.error("Preencha todos os campos corretamente.")
        
        # Listar items
        itens = listar_itens_orcamento(orc_id)
        
        if itens:
            st.divider()
            total_itens = sum([item['valor'] for item in itens])
            
            col_info1, col_info2 = st.columns(2)
            col_info1.metric("📦 Total em Produtos", fmt(total_itens))
            col_info2.metric("📉 Disponível", fmt(max(0, orc['valor_limite'] - total_itens)))
            
            st.divider()
            
            for item in itens:
                with st.expander(f"📦 {item['nome_produto']} - {fmt(item['valor'])} ({item['pagas']}/{item['num_parcelas']} parcelas pagas)"):
                    item_data = obter_item_orcamento(item['id'])
                    if item_data:
                        df_parc = item_data['parcelas']
                        
                        # Progresso do item
                        progresso_item = item['pagas'] / item['num_parcelas'] if item['num_parcelas'] > 0 else 0
                        st.progress(progresso_item, text=f"{progresso_item*100:.1f}% pago")
                        
                        # Parcelas
                        st.write("**Parcelas:**")
                        for _, row in df_parc.iterrows():
                            pago = bool(row['pago'])
                            col_n, col_venc, col_val, col_status, col_btn = st.columns([0.5, 1.5, 1.5, 1.5, 1.5])
                            with col_n:
                                st.write(f"**#{int(row['numero_parcela'])}**")
                            with col_venc:
                                st.write(formatar_data(row['data_vencimento']))
                            with col_val:
                                st.write(fmt(row['valor']))
                            with col_status:
                                if pago:
                                    if row['data_pagamento']:
                                        st.success(f"✅ Paga em {formatar_data(row['data_pagamento'])}")
                                    else:
                                        st.success("✅ Paga")
                                else:
                                    st.warning("⏳ Pendente")
                            with col_btn:
                                label = "Desmarcar" if pago else "Marcar Paga"
                                btn_type = "secondary" if pago else "primary"
                                if st.button(label, key=f"toggle_orc_{row['id']}", type=btn_type):
                                    toggle_parcela_orcamento(int(row['id']), pago)
                                    st.rerun()
                        
                        # Deletar item
                        if st.button("🗑️ Remover Produto", key=f"del_item_{item['id']}", type="secondary"):
                            excluir_item_orcamento(item['id'])
                            st.success(f"Produto '{item['nome_produto']}' removido!")
                            st.rerun()
        else:
            st.info("Nenhum produto adicionado a este orçamento.")
        
        st.divider()
        
        # Editar e deletar orçamento
        col_ed_orc1, col_ed_orc2 = st.columns(2)
        with col_ed_orc1:
            with st.expander("📝 Editar Orçamento"):
                new_nome_orc = st.text_input("Nome", value=orc['nome'], key="new_nome_orc")
                new_desc_orc = st.text_input("Descrição", value=orc['descricao'] or "", key="new_desc_orc")
                new_valor_orc = st.number_input("Valor Limite", value=float(orc['valor_limite']), key="new_valor_orc")
                new_inicio_orc = st.date_input("Data Início", value=datetime.strptime(orc['data_inicio'], "%Y-%m-%d").date(), key="new_inicio_orc")
                new_fim_orc = st.date_input("Data Fim", value=datetime.strptime(orc['data_fim'], "%Y-%m-%d").date(), key="new_fim_orc")
                if st.button("Salvar Alterações", key="save_orc"):
                    atualizar_orcamento(orc_id, new_nome_orc, new_desc_orc, new_valor_orc, 
                                      new_inicio_orc.strftime("%Y-%m-%d"), new_fim_orc.strftime("%Y-%m-%d"))
                    st.success("Orçamento atualizado!")
                    st.rerun()
        with col_ed_orc2:
            with st.expander("🗑️ Excluir Orçamento"):
                st.warning(f"Isso irá remover **{orc['nome']}** permanentemente.")
                if st.button("Confirmar exclusão", type="primary", key="excluir_orc"):
                    excluir_orcamento(orc_id)
                    st.success("Orçamento excluído.")
                    st.rerun()

# ===================== TAB 6 — CONFIGURAÇÕES =====================
with tab6:
    st.subheader("👤 Gerenciar Perfis")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        perfis = listar_perfis()
        idx = perfis.index(st.session_state['perfil_ativo']) if st.session_state['perfil_ativo'] in perfis else 0
        escolha = st.selectbox("Trocar Perfil:", perfis, index=idx)
        if st.button("Trocar"):
            st.session_state['perfil_ativo'] = escolha
            st.rerun()
        if st.button("Excluir Perfil Atual"):
            if st.session_state['perfil_ativo'] == "Padrão":
                st.error("O perfil 'Padrão' não pode ser excluído.")
            else:
                conn = sqlite3.connect('financas.db')
                conn.execute("DELETE FROM transacoes WHERE perfil = ?", (st.session_state['perfil_ativo'],))
                conn.execute("DELETE FROM financiamentos WHERE perfil = ?", (st.session_state['perfil_ativo'],))
                conn.execute("DELETE FROM perfis WHERE nome = ?", (st.session_state['perfil_ativo'],))
                conn.commit()
                conn.close()
                st.session_state['perfil_ativo'] = "Padrão"
                st.success("Perfil excluído e dados removidos.")
                st.rerun()
    with col_p2:
        novo = st.text_input("Novo Perfil:")
        if st.button("Criar"):
            if novo:
                adicionar_perfil(novo)
                st.session_state['perfil_ativo'] = novo
                st.rerun()
    
    st.divider()
    if st.button("Limpar Banco de Dados"):
        resetar_banco()
        st.rerun()
