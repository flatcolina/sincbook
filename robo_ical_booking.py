#!/usr/bin/env python3
"""
Robô de Sincronização de Reservas - Booking.com via iCal
=========================================================

Este script sincroniza automaticamente as reservas do Booking.com
através da análise de calendários iCal (.ics).

Configuração:
- Executar em um servidor (ex: Railway) com agendamento (ex: a cada 15 minutos)
- Variáveis de ambiente necessárias:
  - FIREBASE_CREDENTIALS_JSON: JSON com credenciais do Firebase
  - FIREBASE_PROJECT_ID: ID do projeto Firebase

Uso:
  python3 robo_ical_booking.py
"""

import os
import sys
import json
import logging
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import hashlib

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Importar Firebase
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    logger.error("Firebase Admin SDK não instalado. Instale com: pip install firebase-admin")
    sys.exit(1)

# Importar icalendar
try:
    import icalendar
except ImportError:
    logger.error("icalendar não instalado. Instale com: pip install icalendar")
    sys.exit(1)


class RoboIcalBooking:
    """Robô para sincronizar reservas do Booking.com via iCal"""

    def __init__(self):
        """Inicializa o robô"""
        self.db = None
        self.inicializar_firebase()

    def inicializar_firebase(self):
        """Inicializa a conexão com Firebase"""
        try:
            # Tentar obter credenciais do ambiente
            creds_json = os.getenv('FIREBASE_CREDENTIALS_JSON')
            
            if creds_json:
                # Se houver JSON no ambiente, usar
                creds_dict = json.loads(creds_json)
                creds = credentials.Certificate(creds_dict)
            else:
                # Tentar usar arquivo padrão
                creds_path = 'firebase-credentials.json'
                if not os.path.exists(creds_path):
                    logger.error(f"Arquivo de credenciais não encontrado: {creds_path}")
                    logger.error("Defina FIREBASE_CREDENTIALS_JSON ou crie firebase-credentials.json")
                    sys.exit(1)
                
                creds = credentials.Certificate(creds_path)

            # Inicializar Firebase
            if not firebase_admin.get_app():
                firebase_admin.initialize_app(creds)
            
            self.db = firestore.client()
            logger.info("✅ Firebase inicializado com sucesso")
        except Exception as e:
            logger.error(f"❌ Erro ao inicializar Firebase: {e}")
            sys.exit(1)

    def carregar_configuracoes(self) -> Dict:
        """Carrega as configurações de integração do Firestore"""
        try:
            # Buscar a primeira configuração (geralmente há apenas uma)
            docs = self.db.collection('integracao_config').stream()
            
            for doc in docs:
                config = doc.to_dict()
                logger.info(f"✅ Configuração carregada: {doc.id}")
                return config
            
            logger.warning("⚠️  Nenhuma configuração encontrada em 'integracao_config'")
            return {}
        except Exception as e:
            logger.error(f"❌ Erro ao carregar configurações: {e}")
            return {}

    def baixar_ical(self, url: str) -> Optional[str]:
        """Baixa um arquivo iCal de uma URL"""
        try:
            logger.info(f"📥 Baixando iCal de: {url}")
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            logger.info(f"✅ iCal baixado com sucesso ({len(response.text)} bytes)")
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Erro ao baixar iCal: {e}")
            return None

    def extrair_eventos(self, ical_content: str) -> List[Dict]:
        """Extrai eventos de um conteúdo iCal"""
        try:
            cal = icalendar.Calendar.from_ical(ical_content)
            eventos = []
            
            for component in cal.walk():
                if component.name == "VEVENT":
                    evento = {
                        'summary': str(component.get('summary', 'Sem título')),
                        'description': str(component.get('description', '')),
                        'dtstart': component.get('dtstart'),
                        'dtend': component.get('dtend'),
                        'uid': str(component.get('uid', '')),
                    }
                    eventos.append(evento)
            
            logger.info(f"✅ {len(eventos)} eventos extraídos do iCal")
            return eventos
        except Exception as e:
            logger.error(f"❌ Erro ao extrair eventos do iCal: {e}")
            return []

    def formatar_data(self, dt) -> str:
        """Formata uma data para YYYY-MM-DD"""
        try:
            if hasattr(dt, 'dt'):
                dt = dt.dt
            
            if isinstance(dt, str):
                return dt.split('T')[0]
            
            if hasattr(dt, 'strftime'):
                return dt.strftime('%Y-%m-%d')
            
            return str(dt)[:10]
        except Exception as e:
            logger.warning(f"⚠️  Erro ao formatar data: {e}")
            return ''

    def extrair_dados_evento(self, evento: Dict) -> Optional[Dict]:
        """Extrai dados relevantes de um evento"""
        try:
            nome = evento.get('summary', 'Hóspede Importado')
            data_checkin = self.formatar_data(evento.get('dtstart'))
            data_checkout = self.formatar_data(evento.get('dtend'))
            codigo_reserva = evento.get('uid', f"{nome}-{data_checkin}")

            if not data_checkin or not data_checkout:
                logger.warning(f"⚠️  Evento sem datas válidas: {nome}")
                return None

            return {
                'nome': nome,
                'dataCheckin': data_checkin,
                'dataCheckout': data_checkout,
                'codigoReserva': codigo_reserva
            }
        except Exception as e:
            logger.error(f"❌ Erro ao extrair dados do evento: {e}")
            return None

    def verificar_reserva_existente(self, apartamento_id: str, codigo_reserva: str, origem: str) -> bool:
        """Verifica se uma reserva já existe no Firestore"""
        try:
            docs = self.db.collection('pre_reservas').where(
                'apartamentoId', '==', apartamento_id
            ).where(
                'codigoReservaOrigem', '==', codigo_reserva
            ).where(
                'origem', '==', origem
            ).stream()

            existe = len(list(docs)) > 0
            
            if existe:
                logger.info(f"ℹ️  Reserva {codigo_reserva} já existe, pulando...")
            
            return existe
        except Exception as e:
            logger.error(f"❌ Erro ao verificar reserva existente: {e}")
            return False

    def criar_pre_reserva(self, dados: Dict, apartamento_id: str, origem: str) -> bool:
        """Cria uma pré-reserva no Firestore"""
        try:
            pre_reserva = {
                'nome': dados['nome'],
                'dataCheckin': dados['dataCheckin'],
                'dataCheckout': dados['dataCheckout'],
                'apartamentoId': apartamento_id,
                'origem': origem,
                'codigoReservaOrigem': dados['codigoReserva'],
                'status': 'pendente_validacao',
                'criadoEm': firestore.SERVER_TIMESTAMP
            }

            doc_ref = self.db.collection('pre_reservas').add(pre_reserva)
            logger.info(f"✅ Pré-reserva criada: {dados['codigoReserva']}")
            return True
        except Exception as e:
            logger.error(f"❌ Erro ao criar pré-reserva: {e}")
            return False

    def sincronizar_ical(self, url: str, apartamento_id: str, origem: str = 'booking') -> int:
        """Sincroniza um iCal com o Firestore"""
        logger.info(f"🔄 Sincronizando iCal para apartamento {apartamento_id}")
        
        # Baixar iCal
        ical_content = self.baixar_ical(url)
        if not ical_content:
            return 0

        # Extrair eventos
        eventos = self.extrair_eventos(ical_content)
        if not eventos:
            logger.warning("⚠️  Nenhum evento encontrado no iCal")
            return 0

        # Processar cada evento
        criadas = 0
        for evento in eventos:
            dados = self.extrair_dados_evento(evento)
            if not dados:
                continue

            # Verificar se já existe
            if self.verificar_reserva_existente(apartamento_id, dados['codigoReserva'], origem):
                continue

            # Criar pré-reserva
            if self.criar_pre_reserva(dados, apartamento_id, origem):
                criadas += 1

        logger.info(f"✅ {criadas} novas pré-reservas criadas para {apartamento_id}")
        return criadas

    def executar(self):
        """Executa o robô de sincronização"""
        logger.info("=" * 60)
        logger.info("🤖 Robô de Sincronização - Booking.com via iCal")
        logger.info("=" * 60)

        try:
            # Carregar configurações
            config = self.carregar_configuracoes()
            if not config:
                logger.warning("⚠️  Nenhuma configuração encontrada. Abortando.")
                return

            # Buscar URLs iCal do Booking
            ical_urls = config.get('icalUrls', [])
            urls_booking = [
                url for url in ical_urls
                if url.get('plataforma') == 'booking'
            ]

            if not urls_booking:
                logger.info("ℹ️  Nenhuma URL iCal do Booking configurada")
                return

            logger.info(f"📋 Processando {len(urls_booking)} URL(s) iCal do Booking")

            total_criadas = 0
            for ical_config in urls_booking:
                url = ical_config.get('url')
                apartamento_id = ical_config.get('apartamentoId')
                
                if not url or not apartamento_id:
                    logger.warning("⚠️  URL ou apartamento_id inválido, pulando...")
                    continue

                criadas = self.sincronizar_ical(url, apartamento_id, 'booking')
                total_criadas += criadas

            logger.info("=" * 60)
            logger.info(f"✅ Sincronização concluída: {total_criadas} pré-reservas criadas")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"❌ Erro durante a sincronização: {e}")
            sys.exit(1)


def main():
    """Função principal"""
    robo = RoboIcalBooking()
    robo.executar()


if __name__ == '__main__':
    main()
