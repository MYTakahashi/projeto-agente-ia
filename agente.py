"""
Agente de IA - Oficina Mecânica "Auto Fácil"
=============================================
Protótipo de assistente de agendamento que roda no terminal, usando um LLM local (Ollama + llama3.2).

Fluxo:
  mensagem do cliente -> LLM (llama3.2) extrai horário/serviço
  -> ferramenta ver_horarios_livres() -> validação
  -> confirmação humana (S/N) -> salva em agendamentos.txt

Regras:
  - Máximo de 3 tentativas do cliente.
  - O agendamento SÓ é salvo se a equipe responder "S".
"""

# Bibliotecas
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta
import ollama

# ----------------------------------------------------------------------
# CONFIGURAÇÕES GERAIS
# ----------------------------------------------------------------------

# Modelo local do Ollama
MODELO = os.environ.get("OLLAMA_MODEL", "llama3.2")
# Número máximo de tentativas do cliente antes de encerrar
MAX_TENTATIVAS = 3
ARQUIVO_AGENDAMENTOS = "agendamentos.txt"
# Mensagens padrão de funcioanmento
MSG_HORARIO_FUNCIONAMENTO = (
    "O horário de funcionamento da oficina é de segunda a sexta-feira, "
    "das 8h às 18h. Não abrimos finais de semana e feriados."
)
# Mensagem padrão de falha final (quando o cliente esgota as tentativas)
MSG_FALHA_FINAL = (
    "Infelizmente não consegui te atender. "
    "Agradeço o seu contato, tente novamente mais tarde."
)

# Expediente da oficina (usado na validação)
ABERTURA = "08:00"
FECHAMENTO = "18:00"

# Serviços disponíveis (id -> nome)
SERVICOS = {
    "revisao": "Revisão geral",
    "oleo": "Troca de óleo e filtros",
    "freios": "Revisão de freios",
    "alinhamento": "Alinhamento e balanceamento",
    "suspensao": "Revisão de suspensão",
    "diagnostico": "Diagnóstico com scanner",
}

# Dias da semana (em português, sem acento) na ordem do datetime.weekday()
DIAS_SEMANA = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]


# ----------------------------------------------------------------------
# FERRAMENTAS DO AGENTE
# ----------------------------------------------------------------------
# Função da ferramenta simulando os horários livres.
def ver_horarios_livres():
    return ["08:00", "09:00", "10:00", "13:00", "15:00", "16:00", "17:00"]
# Função da ferramenta simulando os serviços disponíveis.
def listar_servicos():
    return dict(SERVICOS)
# Função da ferramenta que salva o agendamento no arquivo agendamentos.txt, após a confirmação humana.
def agendar_horario(nome, dia, horario, servico_id):
    registro = (
        f"{datetime.now():%Y-%m-%d %H:%M:%S} | Cliente: {nome} | "
        f"Dia: {dia or 'não informado'} | Horário: {formatar_horario(horario)} | "
        f"Serviço: {SERVICOS[servico_id]}\n"
    )
    with open(ARQUIVO_AGENDAMENTOS, "a", encoding="utf-8") as arquivo:
        arquivo.write(registro)

# ----------------------------------------------------------------------
# FUNÇÕES AUXILIARES
# ----------------------------------------------------------------------
# Função para remover acentos e normalizar texto para comparação.
def sem_acento(texto):
    texto = unicodedata.normalize("NFD", str(texto).lower().strip())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")
# Função para formatar horário de 'HH:MM' para 'HHh' ou 'HHhMM'.
def formatar_horario(horario):
    """Converte '14:00' em '14h' e '14:30' em '14h30'."""
    h, m = horario.split(":")
    return f"{int(h):02d}h" if m == "00" else f"{int(h):02d}h{m}"
# Função para gerar texto com horários livres formatados.
def texto_horarios_livres():
    return ", ".join(formatar_horario(h) for h in ver_horarios_livres())
# Função para gerar texto com serviços disponíveis formatados.
def texto_servicos():
    return "\n".join(f"  - {nome}" for nome in listar_servicos().values())
# Função para normalizar horário informado pelo cliente.
def normalizar_horario(valor):
    if valor is None:
        return None
    texto = str(valor).strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})(?:[:h](\d{2})?)?(?:h)?", texto)
    if not m:
        return None
    hora, minuto = int(m.group(1)), int(m.group(2) or 0)
    if hora > 23 or minuto > 59:
        return None
    return f"{hora:02d}:{minuto:02d}"
# Função para normalizar serviço informado pelo cliente.
def normalizar_servico(valor):
    """Aceita o id ('oleo') ou o nome ('Troca de óleo e filtros'); devolve o id ou None."""
    if not valor:
        return None
    v = sem_acento(valor)
    for sid, nome in SERVICOS.items():
        if v == sid or v == sem_acento(nome):
            return sid
    return None
# Função para chamar o LLM (Ollama) e obter a resposta.
def chamar_llm(mensagens, em_json=False):
    """Envia um pedido ao Ollama (llama3.2) e devolve o texto da resposta."""
    resposta = ollama.chat(
        model=MODELO,
        messages=mensagens,
        format="json" if em_json else "",
        options={"temperature": 0},  # respostas mais estáveis
    )
    return resposta["message"]["content"].strip()


# ----------------------------------------------------------------------
# PASSO 1: LLM entende o pedido do cliente
# ----------------------------------------------------------------------
# Função que usa o LLM para extrair horário, serviço e dia da semana da mensagem do cliente.
def extrair_pedido(mensagem):
    hoje = datetime.now()
    amanha = hoje + timedelta(days=1)
    servicos_txt = "\n".join(f'- "{sid}": {nome}' for sid, nome in SERVICOS.items())
# O LLM recebe instruções detalhadas para extrair as informações do pedido do cliente e responder em formato JSON.
    instrucao = f"""Você extrai dados de pedidos de agendamento de uma oficina mecânica.
Hoje é {DIAS_SEMANA[hoje.weekday()]} ({hoje:%d/%m/%Y}). Amanhã é {DIAS_SEMANA[amanha.weekday()]}.

Serviços válidos (use apenas o id):
{servicos_txt}

Responda SOMENTE com um JSON com estas 3 chaves:
{{"horario": "HH:MM" ou null, "servico": "id" ou null, "dia_semana": "segunda|terca|quarta|quinta|sexta|sabado|domingo" ou null}}

Regras:
- "horario" no formato 24h "HH:MM". Se o cliente não disser horário, use null. NÃO invente.
- "servico" deve ser um dos ids acima. Se o serviço pedido não existir na lista ou não foi dito, use null.
- "dia_semana": só preencha se o cliente citar um dia (ou "hoje"/"amanhã"). Senão, null.

Exemplos:
Cliente: Quero marcar uma troca de óleo às 14h
{{"horario": "14:00", "servico": "oleo", "dia_semana": null}}
Cliente: Preciso de alinhamento sábado às 9 da manhã
{{"horario": "09:00", "servico": "alinhamento", "dia_semana": "sabado"}}
Cliente: Quero polir o carro às 10h
{{"horario": "10:00", "servico": null, "dia_semana": null}}
Cliente: Quero uma revisão de freios
{{"horario": null, "servico": "freios", "dia_semana": null}}"""

    texto = chamar_llm(
        [
            {"role": "system", "content": instrucao},
            {"role": "user", "content": f"Cliente: {mensagem}"},
        ],
        em_json=True,
    )
    return json.loads(texto)


# ----------------------------------------------------------------------
# PASSO 2: validação (usa a ferramenta ver_horarios_livres)
# ----------------------------------------------------------------------
# Função que valida o pedido extraído pelo LLM, conferindo dia, serviço e horário.
def validar_pedido(dados):
    problemas = []

    # --- Dia da semana ---
    dia = sem_acento(dados.get("dia_semana") or "") or None
    if dia not in DIAS_SEMANA:
        dia = None
    if dia in ("sabado", "domingo"):
        problemas.append(
            f"Desculpe. Você pediu no {dia}, mas a oficina só abre de segunda a sexta-feira."
        )

    # --- Serviço ---
    servico = normalizar_servico(dados.get("servico"))
    if servico is None:
        problemas.append(
            "O serviço não foi informado ou não está entre os serviços disponíveis."
        )

    # --- Horário ---
    horario = normalizar_horario(dados.get("horario"))
    if horario is None:
        problemas.append("O cliente não informou um horário válido.")
    elif not (ABERTURA <= horario < FECHAMENTO):
        problemas.append(
            f"O horário {formatar_horario(horario)} está fora do expediente (8h às 18h)."
        )
        horario = None
    elif horario not in ver_horarios_livres():  # consulta a ferramenta
        problemas.append(f"O horário {formatar_horario(horario)} não está livre.")
        horario = None

    return problemas, horario, servico, dia


# ----------------------------------------------------------------------
# PASSO 3: resposta educada quando algo dá errado
# ----------------------------------------------------------------------
# Função que pede ao LLM uma resposta educada explicando o que deu errado no pedido do cliente.
def responder_erro(problemas):
    detalhes = "\n".join(f"- {p}" for p in problemas)
    instrucao = (
        "Você é a atendente virtual, simpática e educada, da Oficina Mecânica Auto Fácil. "
        "Responda sempre em português do Brasil. "
        "Explique ao cliente, em no máximo 3 frases curtas, o que impediu o agendamento "
        "e peça que tente novamente informando horário e serviço. "
        "Use SOMENTE as informações fornecidas, sem inventar nada. "
        "Mencione os horários livres e os serviços disponíveis."
    )
    conteudo = (
        f"Problemas encontrados:\n{detalhes}\n\n"
        f"Horários livres: {texto_horarios_livres()}\n"
        f"Serviços disponíveis:\n{texto_servicos()}\n"
        f"Funcionamento: {MSG_HORARIO_FUNCIONAMENTO}"
    )
    try:
        return chamar_llm(
            [
                {"role": "system", "content": instrucao},
                {"role": "user", "content": conteudo},
            ]
        )
    except Exception:
        return (
            "Desculpe, não consegui concluir o agendamento. "
            + " ".join(problemas)
            + f"\nHorários livres: {texto_horarios_livres()}."
            + f"\nServiços disponíveis:\n{texto_servicos()}"
            + "\nPor favor, tente novamente informando o horário e o serviço desejados."
        )


# ----------------------------------------------------------------------
# PASSO 4: confirmação humana
# ----------------------------------------------------------------------
# Função que mostra o resumo do agendamento e pede confirmação à equipe (S/N).
def confirmar_com_equipe(resumo):
    print("\n--- RESUMO DO AGENDAMENTO ---")
    print(resumo)
    print("-----------------------------")
    while True:
        resposta = input("[EQUIPE] Confirmar agendamento? (S/N): ").strip().upper()
        if resposta in ("S", "N"):
            return resposta == "S"
        print("Resposta inválida. Digite apenas S ou N.")
# Função que confere se o Ollama está rodando e se o modelo foi baixado.
def verificar_ollama():
    """Confere se o Ollama está rodando e se o modelo foi baixado."""
    try:
        modelos = [m.model for m in ollama.list().models]
    except Exception:
        print("Não consegui conectar ao Ollama. Abra o aplicativo Ollama "
              "(ou rode 'ollama serve') e tente novamente.")
        sys.exit(1)
    if not any(nome.split(":")[0] == MODELO.split(":")[0] for nome in modelos):
        print(f"O modelo '{MODELO}' não foi encontrado. Baixe com: ollama pull {MODELO}")
        sys.exit(1)


# ----------------------------------------------------------------------
# PROGRAMA PRINCIPAL (controle de execução)
# ----------------------------------------------------------------------
# Função principal que controla o fluxo do atendimento.
def main():
    verificar_ollama()

    print("=" * 55)
    print("  OFICINA MECÂNICA AUTO FÁCIL - Agendamento de Revisão")
    print("=" * 55)
    print(MSG_HORARIO_FUNCIONAMENTO)
    print(f"\nServiços disponíveis:\n{texto_servicos()}")
    print(f"\nHorários livres hoje: {texto_horarios_livres()}")

    nome = input("\nOlá! Qual é o seu nome? ").strip() or "Cliente"

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        print(f"\n(Tentativa {tentativa} de {MAX_TENTATIVAS})")
        mensagem = input(f"{nome}, informe o horário e o serviço que deseja: ").strip()

        if not mensagem:
            problemas, horario, servico, dia = (
                ["O cliente enviou uma mensagem vazia."], None, None, None,
            )
        else:
            try:
                # 1) LLM entende o pedido
                dados = extrair_pedido(mensagem)
                # 2) Validação com a ferramenta de horários
                problemas, horario, servico, dia = validar_pedido(dados)
            except Exception:
                problemas, horario, servico, dia = (
                    ["Houve um problema técnico ao interpretar a mensagem."],
                    None, None, None,
                )

        # Tudo certo: segue para a confirmação humana
        if not problemas:
            resumo = (
                f"Cliente : {nome}\n"
                f"Serviço : {SERVICOS[servico]}\n"
                f"Horário : {formatar_horario(horario)}"
                + (f"\nDia     : {dia}" if dia else "")
            )
            if confirmar_com_equipe(resumo):
                agendar_horario(nome, dia, horario, servico)
                print(f"\nAgendamento confirmado e salvo em {ARQUIVO_AGENDAMENTOS}. Até breve!")
            else:
                print("\nAgendamento cancelado pela equipe. Se quiser, entre em contato novamente.")
            return

        # Deu errado: última tentativa encerra; senão, explica e deixa tentar de novo
        if tentativa == MAX_TENTATIVAS:
            print(f"\n{MSG_FALHA_FINAL}")
            return
        print(f"\nAtendente: {responder_erro(problemas)}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nAtendimento encerrado. Até logo!")
