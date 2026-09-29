#!/usr/bin/env python3
"""Template translations for Resources/Localizable.xcstrings (es, pt-BR, de, fr, tr).

English is the source and fallback. Rows: key → (es, pt-BR, de, fr, tr). Informal address
(tú / você / du / tu / sen). Positional specifiers (%1$@) only where word order changes.
Semantic keys (offer.anchor.*) carry their English value in EN. Keys only used by an optional
module carry a `[module:<flag>]` comment; the scaffold drops them when the module is off.

Re-run after adding keys: python3 Scripts/translations.py — it only fills languages that are
still missing, so reviewed copy in the catalog always wins.
"""
import json
import os

LANGS = ["es", "pt-BR", "de", "fr", "tr"]

T = {
    # --- paywall / pricing ---
    "%@ / month": ("%@ / mes", "%@ / mês", "%@ / Monat", "%@ / mois", "%@ / ay"),
    "%@ / week": ("%@ / semana", "%@ / semana", "%@ / Woche", "%@ / semaine", "%@ / hafta"),
    "%@ / year": ("%@ / año", "%@ / ano", "%@ / Jahr", "%@ / an", "%@ / yıl"),
    "%lld days free": ("%lld días gratis", "%lld dias grátis", "%lld Tage gratis", "%lld jours gratuits", "%lld gün ücretsiz"),
    "%lld days free, then %@ · Cancel anytime": (
        "%lld días gratis, luego %@ · Cancela cuando quieras",
        "%lld dias grátis, depois %@ · Cancele quando quiser",
        "%lld Tage gratis, dann %@ · Jederzeit kündbar",
        "%lld jours gratuits, puis %@ · Résiliable à tout moment",
        "%lld gün ücretsiz, sonra %@ · İstediğin zaman iptal et"),
    "%lld%% OFF": ("%lld%% DE DESCUENTO", "%lld%% OFF", "%lld%% RABATT", "-%lld%%", "%%%lld İNDİRİM"),
    "SAVE %lld%%": ("AHORRA %lld%%", "ECONOMIZE %lld%%", "SPARE %lld%%", "ÉCONOMISE %lld%%", "%%%lld TASARRUF"),
    "Billed %@ · Cancel anytime": ("Se cobra %@ · Cancela cuando quieras", "Cobrança de %@ · Cancele quando quiser",
                                   "Abrechnung: %@ · Jederzeit kündbar", "Facturé %@ · Résiliable à tout moment",
                                   "%@ faturalandırılır · İstediğin zaman iptal et"),
    "Billed weekly": ("Cobro semanal", "Cobrança semanal", "Wöchentliche Abrechnung", "Facturé chaque semaine", "Haftalık faturalandırılır"),
    "Weekly": ("Semanal", "Semanal", "Wöchentlich", "Hebdomadaire", "Haftalık"),
    "Monthly": ("Mensual", "Mensal", "Monatlich", "Mensuel", "Aylık"),
    "Yearly": ("Anual", "Anual", "Jährlich", "Annuel", "Yıllık"),
    "per month": ("al mes", "por mês", "pro Monat", "par mois", "aylık"),
    "Start my free trial": ("Empezar mi prueba gratis", "Começar meu teste grátis", "Gratis-Test starten",
                            "Commencer mon essai gratuit", "Ücretsiz denememi başlat"),
    "Continue": ("Continuar", "Continuar", "Weiter", "Continuer", "Devam"),
    "Claim my offer": ("Aprovechar mi oferta", "Garantir minha oferta", "Angebot sichern", "Profiter de mon offre", "Teklifimi al"),
    "No thanks": ("No, gracias", "Não, obrigado", "Nein, danke", "Non merci", "Hayır, teşekkürler"),
    "ONE-TIME OFFER": ("OFERTA ÚNICA", "OFERTA ÚNICA", "EINMALIGES ANGEBOT", "OFFRE UNIQUE", "TEK SEFERLİK TEKLİF"),
    "One-time offer": ("Oferta única", "Oferta única", "Einmaliges Angebot", "Offre unique", "Tek seferlik teklif"),
    "A one-time price, only right now.": ("Un precio único, solo ahora.", "Um preço único, só agora.",
                                          "Ein einmaliger Preis, nur jetzt.", "Un prix unique, seulement maintenant.",
                                          "Tek seferlik fiyat, sadece şimdi."),
    "Unlock your plan": ("Desbloquea tu plan", "Desbloqueie seu plano", "Schalte deinen Plan frei", "Débloque ton plan", "Planının kilidini aç"),
    "Your goal: %@": ("Tu objetivo: %@", "Seu objetivo: %@", "Dein Ziel: %@", "Ton objectif : %@", "Hedefin: %@"),
    "Your personal plan is ready": ("Tu plan personal está listo", "Seu plano pessoal está pronto", "Dein persönlicher Plan ist fertig",
                                    "Ton plan personnel est prêt", "Kişisel planın hazır"),
    "Built from your answers": ("Creado a partir de tus respuestas", "Criado a partir das suas respostas", "Aus deinen Antworten erstellt",
                                "Créé à partir de tes réponses", "Cevaplarından oluşturuldu"),
    "Built around you": ("Hecho a tu medida", "Feito sob medida para você", "Ganz auf dich zugeschnitten", "Conçu pour toi", "Sana göre hazırlandı"),
    "Personalized results in seconds": ("Resultados personalizados en segundos", "Resultados personalizados em segundos",
                                        "Persönliche Ergebnisse in Sekunden", "Des résultats personnalisés en quelques secondes",
                                        "Saniyeler içinde kişisel sonuçlar"),
    "Everything built from your answers": ("Todo creado a partir de tus respuestas", "Tudo criado a partir das suas respostas",
                                           "Alles aus deinen Antworten erstellt", "Tout est créé à partir de tes réponses",
                                           "Her şey cevaplarına göre"),
    "New insights every day": ("Nuevas ideas cada día", "Novos insights todos os dias", "Jeden Tag neue Einblicke",
                               "De nouvelles idées chaque jour", "Her gün yeni içgörüler"),
    "Cancel anytime": ("Cancela cuando quieras", "Cancele quando quiser", "Jederzeit kündbar", "Résiliable à tout moment", "İstediğin zaman iptal et"),
    "Close": ("Cerrar", "Fechar", "Schließen", "Fermer", "Kapat"),
    "Restore": ("Restaurar", "Restaurar", "Wiederherstellen", "Restaurer", "Geri yükle"),
    "Terms of Use": ("Términos de uso", "Termos de uso", "Nutzungsbedingungen", "Conditions d'utilisation", "Kullanım Koşulları"),
    "Privacy Policy": ("Política de privacidad", "Política de privacidade", "Datenschutzerklärung", "Politique de confidentialité", "Gizlilik Politikası"),
    "Purchase received. Your plan will unlock shortly — reopen the app or tap Restore.": (
        "Compra recibida. Tu plan se desbloqueará en breve: vuelve a abrir la app o toca Restaurar.",
        "Compra recebida. Seu plano será desbloqueado em breve — reabra o app ou toque em Restaurar.",
        "Kauf erhalten. Dein Plan wird gleich freigeschaltet – öffne die App erneut oder tippe auf Wiederherstellen.",
        "Achat reçu. Ton plan sera débloqué sous peu — rouvre l'app ou touche Restaurer.",
        "Satın alma alındı. Planın birazdan açılacak; uygulamayı yeniden aç ya da Geri yükle'ye dokun."),
    "The purchase didn't go through. Please try again.": (
        "La compra no se completó. Inténtalo de nuevo.", "A compra não foi concluída. Tente novamente.",
        "Der Kauf hat nicht geklappt. Bitte versuche es erneut.", "L'achat n'a pas abouti. Réessaie.",
        "Satın alma tamamlanamadı. Lütfen tekrar dene."),
    "The store isn't available right now. Please check your connection and try again.": (
        "La tienda no está disponible ahora. Revisa tu conexión e inténtalo de nuevo.",
        "A loja não está disponível agora. Verifique sua conexão e tente novamente.",
        "Der Store ist gerade nicht verfügbar. Prüfe deine Verbindung und versuche es erneut.",
        "La boutique n'est pas disponible pour le moment. Vérifie ta connexion et réessaie.",
        "Mağaza şu anda kullanılamıyor. Bağlantını kontrol edip tekrar dene."),
    # --- billing issue ---
    "There's a problem with your payment": ("Hay un problema con tu pago", "Há um problema com seu pagamento",
                                            "Es gibt ein Problem mit deiner Zahlung", "Il y a un problème avec ton paiement",
                                            "Ödemende bir sorun var"),
    "Your subscription is on hold": ("Tu suscripción está en pausa", "Sua assinatura está suspensa", "Dein Abo ist pausiert",
                                     "Ton abonnement est suspendu", "Aboneliğin askıda"),
    "Update your payment method to keep Premium.": (
        "Actualiza tu método de pago para mantener Premium.", "Atualize sua forma de pagamento para manter o Premium.",
        "Aktualisiere deine Zahlungsmethode, um Premium zu behalten.", "Mets à jour ton moyen de paiement pour garder Premium.",
        "Premium'u korumak için ödeme yöntemini güncelle."),
    "See plans": ("Ver planes", "Ver planos", "Pläne ansehen", "Voir les offres", "Planları gör"),
    # --- onboarding ---
    "Your personal AI, ready in seconds": ("Tu IA personal, lista en segundos", "Sua IA pessoal, pronta em segundos",
                                           "Deine persönliche KI, in Sekunden bereit", "Ton IA personnelle, prête en quelques secondes",
                                           "Kişisel yapay zekân, saniyeler içinde hazır"),
    "Answer a few quick questions and we'll build a plan around you.": (
        "Responde unas preguntas rápidas y crearemos un plan a tu medida.",
        "Responda algumas perguntas rápidas e criaremos um plano sob medida para você.",
        "Beantworte ein paar kurze Fragen und wir erstellen einen Plan für dich.",
        "Réponds à quelques questions rapides et nous créerons un plan pour toi.",
        "Birkaç kısa soruyu yanıtla, sana özel bir plan hazırlayalım."),
    "Get started": ("Empezar", "Começar", "Los geht's", "Commencer", "Başla"),
    "What's your main goal?": ("¿Cuál es tu objetivo principal?", "Qual é o seu objetivo principal?", "Was ist dein wichtigstes Ziel?",
                               "Quel est ton objectif principal ?", "Ana hedefin ne?"),
    "We'll shape everything around it.": ("Adaptaremos todo a él.", "Vamos adaptar tudo a ele.", "Wir richten alles danach aus.",
                                          "Nous adapterons tout en fonction.", "Her şeyi buna göre şekillendireceğiz."),
    "Look and feel my best": ("Verme y sentirme lo mejor posible", "Ficar e me sentir o melhor possível", "Bestmöglich aussehen und mich gut fühlen",
                              "Être au top et me sentir bien", "En iyi halimle görünmek ve hissetmek"),
    "Save time": ("Ahorrar tiempo", "Economizar tempo", "Zeit sparen", "Gagner du temps", "Zaman kazanmak"),
    "Learn something new": ("Aprender algo nuevo", "Aprender algo novo", "Etwas Neues lernen", "Apprendre quelque chose de nouveau", "Yeni bir şey öğrenmek"),
    "Just curious": ("Solo por curiosidad", "Só curiosidade", "Nur neugierig", "Simple curiosité", "Sadece merak ediyorum"),
    "Where did you hear about us?": ("¿Dónde nos conociste?", "Onde você nos conheceu?", "Wie hast du von uns erfahren?",
                                     "Comment nous as-tu connus ?", "Bizi nereden duydun?"),
    "TikTok": ("TikTok", "TikTok", "TikTok", "TikTok", "TikTok"),
    "Instagram": ("Instagram", "Instagram", "Instagram", "Instagram", "Instagram"),
    "YouTube": ("YouTube", "YouTube", "YouTube", "YouTube", "YouTube"),
    "App Store": ("App Store", "App Store", "App Store", "App Store", "App Store"),
    "Google": ("Google", "Google", "Google", "Google", "Google"),
    "Friend or family": ("Amigos o familia", "Amigos ou família", "Freunde oder Familie", "Amis ou famille", "Arkadaş veya aile"),
    "Other": ("Otro", "Outro", "Andere", "Autre", "Diğer"),
    "How familiar are you with this?": ("¿Cuánto sabes sobre esto?", "Quanto você conhece disso?", "Wie vertraut bist du damit?",
                                        "Quel est ton niveau sur le sujet ?", "Bu konuya ne kadar aşinasın?"),
    "There are no wrong answers.": ("No hay respuestas incorrectas.", "Não existem respostas erradas.", "Es gibt keine falschen Antworten.",
                                    "Il n'y a pas de mauvaise réponse.", "Yanlış cevap yok."),
    "I'm just starting": ("Estoy empezando", "Estou começando", "Ich fange gerade an", "Je débute", "Yeni başlıyorum"),
    "I know the basics": ("Conozco lo básico", "Conheço o básico", "Ich kenne die Grundlagen", "Je connais les bases", "Temel bilgileri biliyorum"),
    "I'm an expert": ("Soy experto", "Sou especialista", "Ich bin Profi", "Je suis expert", "Uzmanım"),
    "How it works": ("Cómo funciona", "Como funciona", "So funktioniert's", "Comment ça marche", "Nasıl çalışır"),
    "Three simple steps, every time.": ("Tres pasos sencillos, siempre.", "Três passos simples, sempre.", "Drei einfache Schritte, jedes Mal.",
                                        "Trois étapes simples, à chaque fois.", "Her seferinde üç basit adım."),
    "Take or pick a photo": ("Toma o elige una foto", "Tire ou escolha uma foto", "Mach oder wähle ein Foto", "Prends ou choisis une photo",
                             "Fotoğraf çek ya da seç"),
    "Our AI analyzes it in seconds": ("Nuestra IA la analiza en segundos", "Nossa IA analisa em segundos", "Unsere KI analysiert es in Sekunden",
                                      "Notre IA l'analyse en quelques secondes", "Yapay zekâmız saniyeler içinde analiz eder"),
    "Get results made for you": ("Recibe resultados hechos para ti", "Receba resultados feitos para você", "Erhalte Ergebnisse, die zu dir passen",
                                 "Obtiens des résultats faits pour toi", "Sana özel sonuçlar al"),
    "What year were you born?": ("¿En qué año naciste?", "Em que ano você nasceu?", "In welchem Jahr bist du geboren?",
                                 "En quelle année es-tu né·e ?", "Hangi yıl doğdun?"),
    "We use this to tailor your results.": ("Lo usamos para adaptar tus resultados.", "Usamos isso para personalizar seus resultados.",
                                            "Damit passen wir deine Ergebnisse an.", "Nous l'utilisons pour adapter tes résultats.",
                                            "Sonuçlarını buna göre uyarlıyoruz."),
    "How often would you use the app?": ("¿Con qué frecuencia usarías la app?", "Com que frequência você usaria o app?",
                                         "Wie oft würdest du die App nutzen?", "À quelle fréquence utiliserais-tu l'app ?",
                                         "Uygulamayı ne sıklıkla kullanırsın?"),
    "Every day": ("Todos los días", "Todos os dias", "Jeden Tag", "Tous les jours", "Her gün"),
    "A few times a week": ("Varias veces por semana", "Algumas vezes por semana", "Ein paar Mal pro Woche", "Quelques fois par semaine", "Haftada birkaç kez"),
    "Now and then": ("De vez en cuando", "De vez em quando", "Ab und zu", "De temps en temps", "Ara sıra"),
    "You're in the right place": ("Estás en el lugar indicado", "Você está no lugar certo", "Du bist hier genau richtig",
                                  "Tu es au bon endroit", "Doğru yerdesin"),
    "People with goals like yours make progress one small step at a time.": (
        "Las personas con objetivos como el tuyo avanzan paso a paso.",
        "Pessoas com objetivos como o seu avançam um pequeno passo de cada vez.",
        "Menschen mit Zielen wie deinem kommen Schritt für Schritt voran.",
        "Les personnes qui ont des objectifs comme le tien progressent petit à petit.",
        "Senin gibi hedefleri olan insanlar küçük adımlarla ilerler."),
    "How much time can you spend each day?": ("¿Cuánto tiempo puedes dedicarle cada día?", "Quanto tempo você pode dedicar por dia?",
                                              "Wie viel Zeit hast du pro Tag?", "Combien de temps peux-tu y consacrer chaque jour ?",
                                              "Her gün ne kadar zaman ayırabilirsin?"),
    "Even a few minutes is enough.": ("Incluso unos minutos bastan.", "Até alguns minutos bastam.", "Schon ein paar Minuten reichen.",
                                      "Même quelques minutes suffisent.", "Birkaç dakika bile yeterli."),
    "min": ("min", "min", "Min.", "min", "dk"),
    "What's holding you back?": ("¿Qué te frena?", "O que está te impedindo?", "Was hält dich zurück?", "Qu'est-ce qui te freine ?", "Seni ne durduruyor?"),
    "Select all that apply": ("Selecciona todas las que correspondan", "Selecione todas as opções que se aplicam", "Wähle alles Zutreffende",
                              "Sélectionne toutes les réponses qui s'appliquent", "Uygun olanların hepsini seç"),
    "Not enough time": ("Falta de tiempo", "Falta de tempo", "Zu wenig Zeit", "Pas assez de temps", "Yeterli zaman yok"),
    "Not sure where to start": ("No sé por dónde empezar", "Não sei por onde começar", "Ich weiß nicht, wo ich anfangen soll",
                                "Je ne sais pas par où commencer", "Nereden başlayacağımı bilmiyorum"),
    "Too many choices": ("Demasiadas opciones", "Opções demais", "Zu viele Möglichkeiten", "Trop de choix", "Çok fazla seçenek"),
    "Staying consistent": ("Ser constante", "Manter a constância", "Dranbleiben", "Rester régulier", "İstikrarlı kalmak"),
    "Easier with a plan": ("Más fácil con un plan", "Mais fácil com um plano", "Einfacher mit einem Plan", "Plus facile avec un plan", "Bir planla daha kolay"),
    "A personal plan makes every step clearer than going it alone.": (
        "Un plan personal hace que cada paso sea más claro que hacerlo por tu cuenta.",
        "Um plano pessoal deixa cada passo mais claro do que fazer tudo sozinho.",
        "Mit einem persönlichen Plan ist jeder Schritt klarer als allein.",
        "Un plan personnel rend chaque étape plus claire que de se débrouiller seul.",
        "Kişisel bir plan, her adımı tek başına ilerlemekten daha net kılar."),
    "What matters most to you?": ("¿Qué es lo que más te importa?", "O que mais importa para você?", "Was ist dir am wichtigsten?",
                                  "Qu'est-ce qui compte le plus pour toi ?", "Senin için en önemli olan ne?"),
    "Accuracy": ("Precisión", "Precisão", "Genauigkeit", "Précision", "Doğruluk"),
    "Speed": ("Rapidez", "Rapidez", "Tempo", "Rapidité", "Hız"),
    "Simplicity": ("Sencillez", "Simplicidade", "Einfachheit", "Simplicité", "Sadelik"),
    "Inspiration": ("Inspiración", "Inspiração", "Inspiration", "Inspiration", "İlham"),
    "What would you like to achieve?": ("¿Qué te gustaría lograr?", "O que você gostaria de conquistar?", "Was möchtest du erreichen?",
                                        "Qu'aimerais-tu accomplir ?", "Neyi başarmak istersin?"),
    "Feel more confident": ("Sentirme más seguro", "Me sentir mais confiante", "Selbstbewusster sein", "Avoir plus confiance en moi",
                            "Kendimi daha özgüvenli hissetmek"),
    "Make better choices": ("Tomar mejores decisiones", "Fazer escolhas melhores", "Bessere Entscheidungen treffen", "Faire de meilleurs choix",
                            "Daha iyi seçimler yapmak"),
    "Save money": ("Ahorrar dinero", "Economizar dinheiro", "Geld sparen", "Économiser de l'argent", "Para biriktirmek"),
    "Have fun": ("Divertirme", "Me divertir", "Spaß haben", "M'amuser", "Eğlenmek"),
    "You have great potential": ("Tienes un gran potencial", "Você tem um grande potencial", "Du hast großes Potenzial",
                                 "Tu as un beau potentiel", "Büyük bir potansiyelin var"),
    "Your answers show you're ready. Small daily steps add up.": (
        "Tus respuestas muestran que estás listo. Los pequeños pasos diarios suman.",
        "Suas respostas mostram que você está pronto. Pequenos passos diários fazem diferença.",
        "Deine Antworten zeigen: Du bist bereit. Kleine tägliche Schritte summieren sich.",
        "Tes réponses montrent que tu es prêt·e. Les petits pas quotidiens s'additionnent.",
        "Cevapların hazır olduğunu gösteriyor. Küçük günlük adımlar birikir."),
    "When do you usually have time?": ("¿Cuándo sueles tener tiempo?", "Quando você costuma ter tempo?", "Wann hast du meistens Zeit?",
                                       "Quand as-tu du temps en général ?", "Genellikle ne zaman vaktin olur?"),
    "Morning": ("Por la mañana", "De manhã", "Morgens", "Le matin", "Sabah"),
    "Afternoon": ("Por la tarde", "À tarde", "Nachmittags", "L'après-midi", "Öğleden sonra"),
    "Evening": ("Por la noche", "À noite", "Abends", "Le soir", "Akşam"),
    "It varies": ("Depende", "Varia", "Unterschiedlich", "Ça dépend", "Değişiyor"),
    "Which best describes you?": ("¿Qué te describe mejor?", "O que melhor descreve você?", "Was beschreibt dich am besten?",
                                  "Qu'est-ce qui te décrit le mieux ?", "Seni en iyi ne tanımlar?"),
    "Student": ("Estudiante", "Estudante", "Student:in", "Étudiant·e", "Öğrenci"),
    "Professional": ("Profesional", "Profissional", "Berufstätig", "Professionnel·le", "Profesyonel"),
    "Creator": ("Creador", "Criador", "Creator", "Créateur·rice", "İçerik üretici"),
    "Your privacy matters": ("Tu privacidad importa", "Sua privacidade importa", "Deine Privatsphäre ist uns wichtig",
                             "Ta vie privée compte", "Gizliliğin önemli"),
    "You stay in control of your data.": ("Tú controlas tus datos.", "Você mantém o controle dos seus dados.", "Du behältst die Kontrolle über deine Daten.",
                                          "Tu gardes le contrôle de tes données.", "Verilerinin kontrolü sende."),
    "We never sell your data": ("Nunca vendemos tus datos", "Nunca vendemos seus dados", "Wir verkaufen deine Daten nie",
                                "Nous ne vendons jamais tes données", "Verilerini asla satmayız"),
    "Your answers stay private": ("Tus respuestas son privadas", "Suas respostas ficam privadas", "Deine Antworten bleiben privat",
                                  "Tes réponses restent privées", "Cevapların gizli kalır"),
    "Delete everything anytime in Settings": ("Borra todo cuando quieras en Ajustes", "Apague tudo quando quiser em Ajustes",
                                              "Lösche jederzeit alles in den Einstellungen", "Supprime tout à tout moment dans Réglages",
                                              "Her şeyi istediğin zaman Ayarlar'dan sil"),
    "Allow AI analysis": ("Permitir el análisis con IA", "Permitir a análise por IA", "KI-Analyse erlauben", "Autoriser l'analyse par IA",
                          "Yapay zekâ analizine izin ver"),
    "To personalize your results, your photos and answers are processed by our AI. You can withdraw consent anytime in Settings.": (
        "Para personalizar tus resultados, nuestra IA procesa tus fotos y respuestas. Puedes retirar tu consentimiento en Ajustes cuando quieras.",
        "Para personalizar seus resultados, nossa IA processa suas fotos e respostas. Você pode retirar o consentimento a qualquer momento em Ajustes.",
        "Um deine Ergebnisse zu personalisieren, verarbeitet unsere KI deine Fotos und Antworten. Du kannst deine Einwilligung jederzeit in den Einstellungen widerrufen.",
        "Pour personnaliser tes résultats, notre IA traite tes photos et tes réponses. Tu peux retirer ton consentement à tout moment dans Réglages.",
        "Sonuçlarını kişiselleştirmek için fotoğrafların ve cevapların yapay zekâmız tarafından işlenir. Onayını istediğin zaman Ayarlar'dan geri çekebilirsin."),
    "I agree to AI processing of my photos and answers": (
        "Acepto que la IA procese mis fotos y respuestas", "Concordo com o processamento das minhas fotos e respostas por IA",
        "Ich stimme der KI-Verarbeitung meiner Fotos und Antworten zu", "J'accepte le traitement de mes photos et réponses par l'IA",
        "Fotoğraflarımın ve cevaplarımın yapay zekâ ile işlenmesini kabul ediyorum"),
    "Thank you for trusting us": ("Gracias por confiar en nosotros", "Obrigado por confiar em nós", "Danke für dein Vertrauen",
                                  "Merci de ta confiance", "Bize güvendiğin için teşekkürler"),
    "We'll keep your information private and secure.": ("Mantendremos tu información privada y segura.", "Manteremos suas informações privadas e seguras.",
                                                         "Wir halten deine Daten privat und sicher.", "Nous garderons tes informations privées et sécurisées.",
                                                         "Bilgilerini gizli ve güvende tutacağız."),
    "How do you like your tips?": ("¿Cómo prefieres los consejos?", "Como você prefere as dicas?", "Wie magst du deine Tipps?",
                                   "Comment préfères-tu tes conseils ?", "İpuçlarını nasıl seversin?"),
    "Short and simple": ("Breves y sencillos", "Curtas e simples", "Kurz und einfach", "Courts et simples", "Kısa ve basit"),
    "Detailed": ("Detallados", "Detalhadas", "Ausführlich", "Détaillés", "Ayrıntılı"),
    "Visual": ("Visuales", "Visuais", "Visuell", "Visuels", "Görsel"),
    "Almost there": ("Ya casi", "Quase lá", "Fast geschafft", "Presque fini", "Neredeyse bitti"),
    "We're using your answers to build a plan just for you.": (
        "Estamos usando tus respuestas para crear un plan solo para ti.", "Estamos usando suas respostas para criar um plano só para você.",
        "Wir erstellen aus deinen Antworten einen Plan nur für dich.", "Nous utilisons tes réponses pour créer un plan rien que pour toi.",
        "Cevaplarınla sadece sana özel bir plan hazırlıyoruz."),
    "Setting everything up for you": ("Preparándolo todo para ti", "Preparando tudo para você", "Wir richten alles für dich ein",
                                      "Nous préparons tout pour toi", "Her şeyi senin için hazırlıyoruz"),
    "Analyzing your answers": ("Analizando tus respuestas", "Analisando suas respostas", "Deine Antworten werden analysiert",
                               "Analyse de tes réponses", "Cevapların analiz ediliyor"),
    "Matching your goals": ("Ajustando a tus objetivos", "Ajustando aos seus objetivos", "Abgleich mit deinen Zielen",
                            "Adaptation à tes objectifs", "Hedeflerinle eşleştiriliyor"),
    "Personalizing your plan": ("Personalizando tu plan", "Personalizando seu plano", "Dein Plan wird personalisiert",
                                "Personnalisation de ton plan", "Planın kişiselleştiriliyor"),
    "Your plan is ready!": ("¡Tu plan está listo!", "Seu plano está pronto!", "Dein Plan ist fertig!", "Ton plan est prêt !", "Planın hazır!"),
    "Here's what we built from your answers.": ("Esto es lo que creamos con tus respuestas.", "Veja o que criamos com suas respostas.",
                                                "Das haben wir aus deinen Antworten erstellt.", "Voici ce que nous avons créé à partir de tes réponses.",
                                                "Cevaplarından oluşturduklarımız burada."),
    "Let's go": ("¡Vamos!", "Vamos lá", "Los geht's", "C'est parti", "Hadi başlayalım"),
    "Save your progress": ("Guarda tu progreso", "Salve seu progresso", "Sichere deinen Fortschritt", "Sauvegarde ta progression", "İlerlemeni kaydet"),
    "Sign in with Apple so your plan and purchases follow you to a new phone.": (
        "Inicia sesión con Apple para que tu plan y tus compras te acompañen a un nuevo teléfono.",
        "Entre com a Apple para que seu plano e suas compras acompanhem você em um novo celular.",
        "Melde dich mit Apple an, damit dein Plan und deine Käufe mit auf ein neues Handy kommen.",
        "Connecte-toi avec Apple pour retrouver ton plan et tes achats sur un nouveau téléphone.",
        "Planın ve satın alımların yeni telefonuna da gelsin diye Apple ile giriş yap."),
    "Not now": ("Ahora no", "Agora não", "Nicht jetzt", "Pas maintenant", "Şimdi değil"),
    "Back": ("Atrás", "Voltar", "Zurück", "Retour", "Geri"),
    "Progress": ("Progreso", "Progresso", "Fortschritt", "Progression", "İlerleme"),
    "Metric": ("Métrico", "Métrico", "Metrisch", "Métrique", "Metrik"),
    "Imperial": ("Imperial", "Imperial", "Imperial", "Impérial", "İngiliz"),
    "kg": ("kg", "kg", "kg", "kg", "kg"),
    "lb": ("lb", "lb", "lb", "lb", "lb"),
    "Tell us one more thing": ("Cuéntanos una cosa más", "Conte mais uma coisa", "Verrate uns noch etwas", "Dis-nous encore une chose", "Bize bir şey daha söyle"),
    "It helps us personalize your plan.": ("Nos ayuda a personalizar tu plan.", "Isso nos ajuda a personalizar seu plano.",
                                           "Das hilft uns, deinen Plan zu personalisieren.", "Cela nous aide à personnaliser ton plan.",
                                           "Planını kişiselleştirmemize yardımcı olur."),
    "Yes": ("Sí", "Sim", "Ja", "Oui", "Evet"),
    "No": ("No", "Não", "Nein", "Non", "Hayır"),
    "Not sure": ("No estoy seguro", "Não tenho certeza", "Nicht sicher", "Pas sûr·e", "Emin değilim"),
    # --- main app ---
    "Create": ("Crear", "Criar", "Erstellen", "Créer", "Oluştur"),
    "Gallery": ("Galería", "Galeria", "Galerie", "Galerie", "Galeri"),
    "Settings": ("Ajustes", "Ajustes", "Einstellungen", "Réglages", "Ayarlar"),
    "Everything you've created.": ("Todo lo que has creado.", "Tudo o que você criou.", "Alles, was du erstellt hast.",
                                   "Tout ce que tu as créé.", "Oluşturduğun her şey."),
    "Nothing here yet": ("Aún no hay nada", "Nada por aqui ainda", "Noch nichts hier", "Rien pour l'instant", "Henüz bir şey yok"),
    "Your creations will appear here.": ("Tus creaciones aparecerán aquí.", "Suas criações vão aparecer aqui.", "Deine Kreationen erscheinen hier.",
                                         "Tes créations apparaîtront ici.", "Oluşturdukların burada görünecek."),
    "Share": ("Compartir", "Compartilhar", "Teilen", "Partager", "Paylaş"),
    "Delete": ("Eliminar", "Excluir", "Löschen", "Supprimer", "Sil"),
    "Premium": ("Premium", "Premium", "Premium", "Premium", "Premium"),
    "Pick a photo and let our AI do the rest.": ("Elige una foto y deja que nuestra IA haga el resto.", "Escolha uma foto e deixe nossa IA fazer o resto.",
                                                 "Wähle ein Foto und lass unsere KI den Rest machen.", "Choisis une photo et laisse notre IA faire le reste.",
                                                 "Bir fotoğraf seç, gerisini yapay zekâmıza bırak."),
    "Your photo": ("Tu foto", "Sua foto", "Dein Foto", "Ta photo", "Fotoğrafın"),
    "Choose a photo": ("Elige una foto", "Escolha uma foto", "Foto auswählen", "Choisis une photo", "Fotoğraf seç"),
    "Photos only": ("Solo fotos", "Somente fotos", "Nur Fotos", "Photos uniquement", "Yalnızca fotoğraf"),
    "Please choose a photo. Videos aren't supported.": ("Elige una foto. Los videos no son compatibles.", "Escolha uma foto. Vídeos não são compatíveis.",
                                                        "Bitte wähle ein Foto. Videos werden nicht unterstützt.", "Choisis une photo. Les vidéos ne sont pas prises en charge.",
                                                        "Lütfen bir fotoğraf seç. Videolar desteklenmiyor."),
    "OK": ("OK", "OK", "OK", "OK", "Tamam"),
    "Style": ("Estilo", "Estilo", "Stil", "Style", "Stil"),
    "Natural": ("Natural", "Natural", "Natürlich", "Naturel", "Doğal"),
    "Vivid": ("Vívido", "Vívido", "Lebendig", "Vif", "Canlı"),
    "Soft": ("Suave", "Suave", "Sanft", "Doux", "Yumuşak"),
    "Bold": ("Intenso", "Marcante", "Kräftig", "Audacieux", "Cesur"),
    "Generate": ("Generar", "Gerar", "Erstellen", "Générer", "Oluştur"),
    "Working on it…": ("Trabajando en ello…", "Trabalhando nisso…", "Wird bearbeitet …", "On s'en occupe…", "Üzerinde çalışıyoruz…"),
    "This usually takes a few seconds.": ("Suele tardar unos segundos.", "Isso costuma levar alguns segundos.", "Das dauert meist nur ein paar Sekunden.",
                                          "Cela prend généralement quelques secondes.", "Bu genellikle birkaç saniye sürer."),
    "Your result is ready": ("Tu resultado está listo", "Seu resultado está pronto", "Dein Ergebnis ist fertig", "Ton résultat est prêt", "Sonucun hazır"),
    "Create another": ("Crear otro", "Criar outro", "Noch eins erstellen", "En créer un autre", "Bir tane daha oluştur"),
    "We couldn't finish that right now. Please try again.": (
        "No pudimos terminarlo ahora. Inténtalo de nuevo.", "Não conseguimos concluir agora. Tente novamente.",
        "Das hat gerade nicht geklappt. Bitte versuche es erneut.", "Nous n'avons pas pu terminer pour le moment. Réessaie.",
        "Şu anda tamamlayamadık. Lütfen tekrar dene."),
    "This photo isn't something we can analyze. Try another one.": (
        "No podemos analizar esta foto. Prueba con otra.", "Não conseguimos analisar esta foto. Tente outra.",
        "Dieses Foto können wir nicht analysieren. Versuch ein anderes.", "Nous ne pouvons pas analyser cette photo. Essaie une autre.",
        "Bu fotoğrafı analiz edemiyoruz. Başka bir tane dene."),
    "You've reached today's limit. It resets at %@.": (
        "Has alcanzado el límite de hoy. Se restablece a las %@.", "Você atingiu o limite de hoje. Ele é renovado às %@.",
        "Du hast das heutige Limit erreicht. Es wird um %@ zurückgesetzt.", "Tu as atteint la limite du jour. Elle se réinitialise à %@.",
        "Bugünkü sınıra ulaştın. %@ itibarıyla sıfırlanır."),
    "You've reached today's limit. Please come back tomorrow.": (
        "Has alcanzado el límite de hoy. Vuelve mañana.", "Você atingiu o limite de hoje. Volte amanhã.",
        "Du hast das heutige Limit erreicht. Komm morgen wieder.", "Tu as atteint la limite du jour. Reviens demain.",
        "Bugünkü sınıra ulaştın. Lütfen yarın tekrar gel."),
    "Too many attempts. Please try again later.": ("Demasiados intentos. Inténtalo más tarde.", "Tentativas demais. Tente novamente mais tarde.",
                                                   "Zu viele Versuche. Bitte versuche es später erneut.", "Trop de tentatives. Réessaie plus tard.",
                                                   "Çok fazla deneme. Lütfen daha sonra tekrar dene."),
    "We couldn't verify your subscription right now. Please try again.": (
        "No pudimos verificar tu suscripción ahora. Inténtalo de nuevo.", "Não conseguimos verificar sua assinatura agora. Tente novamente.",
        "Wir konnten dein Abo gerade nicht prüfen. Bitte versuche es erneut.", "Nous n'avons pas pu vérifier ton abonnement. Réessaie.",
        "Aboneliğini şu anda doğrulayamadık. Lütfen tekrar dene."),
    # --- settings ---
    "Account": ("Cuenta", "Conta", "Konto", "Compte", "Hesap"),
    "Subscription": ("Suscripción", "Assinatura", "Abo", "Abonnement", "Abonelik"),
    "Active": ("Activa", "Ativa", "Aktiv", "Actif", "Aktif"),
    "Free": ("Gratis", "Grátis", "Kostenlos", "Gratuit", "Ücretsiz"),
    "Upgrade to Premium": ("Pásate a Premium", "Assine o Premium", "Auf Premium upgraden", "Passer à Premium", "Premium'a geç"),
    "Restore Purchases": ("Restaurar compras", "Restaurar compras", "Käufe wiederherstellen", "Restaurer les achats", "Satın alımları geri yükle"),
    "Manage Subscription": ("Gestionar suscripción", "Gerenciar assinatura", "Abo verwalten", "Gérer l'abonnement", "Aboneliği yönet"),
    "Privacy": ("Privacidad", "Privacidade", "Datenschutz", "Confidentialité", "Gizlilik"),
    "Withdraw AI consent": ("Retirar el consentimiento de IA", "Retirar o consentimento de IA", "KI-Einwilligung widerrufen",
                            "Retirer le consentement IA", "Yapay zekâ onayını geri çek"),
    "About": ("Acerca de", "Sobre", "Info", "À propos", "Hakkında"),
    "Contact Support": ("Contactar con soporte", "Falar com o suporte", "Support kontaktieren", "Contacter l'assistance", "Destek ile iletişime geç"),
    "Delete account": ("Eliminar cuenta", "Excluir conta", "Konto löschen", "Supprimer le compte", "Hesabı sil"),
    "Cancel": ("Cancelar", "Cancelar", "Abbrechen", "Annuler", "Vazgeç"),
    "This deletes your data for good. It does not cancel your App Store subscription: cancel it in Settings → Apple ID → Subscriptions.": (
        "Esto borra tus datos para siempre. No cancela tu suscripción del App Store: cancélala en Ajustes → ID de Apple → Suscripciones.",
        "Isso apaga seus dados para sempre. Não cancela sua assinatura da App Store: cancele em Ajustes → ID Apple → Assinaturas.",
        "Damit werden deine Daten endgültig gelöscht. Dein App-Store-Abo wird nicht gekündigt: Kündige es unter Einstellungen → Apple-ID → Abonnements.",
        "Cela supprime définitivement tes données. Ton abonnement App Store n'est pas résilié : résilie-le dans Réglages → Identifiant Apple → Abonnements.",
        "Bu, verilerini kalıcı olarak siler. App Store aboneliğini iptal etmez: Ayarlar → Apple Kimliği → Abonelikler'den iptal et."),
    "We couldn't delete your account. Please try again.": (
        "No pudimos eliminar tu cuenta. Inténtalo de nuevo.", "Não conseguimos excluir sua conta. Tente novamente.",
        "Wir konnten dein Konto nicht löschen. Bitte versuche es erneut.", "Nous n'avons pas pu supprimer ton compte. Réessaie.",
        "Hesabını silemedik. Lütfen tekrar dene."),
    "Version": ("Versión", "Versão", "Version", "Version", "Sürüm"),
}

# Semantic keys: English value + translations.
SEMANTIC = {
    "offer.anchor.burger": ("Less than one burger a month", "Menos que una hamburguesa al mes", "Menos que um hambúrguer por mês",
                            "Weniger als ein Burger im Monat", "Moins qu'un burger par mois", "Ayda bir hamburgerden az"),
    "offer.anchor.coffee": ("Less than one coffee a month", "Menos que un café al mes", "Menos que um café por mês",
                            "Weniger als ein Kaffee im Monat", "Moins qu'un café par mois", "Ayda bir kahveden az"),
    "offer.anchor.pizza": ("Less than one pizza a month", "Menos que una pizza al mes", "Menos que uma pizza por mês",
                           "Weniger als eine Pizza im Monat", "Moins qu'une pizza par mois", "Ayda bir pizzadan az"),
    "offer.anchor.movie": ("Less than one movie ticket a month", "Menos que una entrada de cine al mes", "Menos que um ingresso de cinema por mês",
                           "Weniger als ein Kinoticket im Monat", "Moins qu'une place de cinéma par mois", "Ayda bir sinema biletinden az"),
}

# Optional modules: key → (flag, (es, pt-BR, de, fr, tr)).
MODULE = {
    "Connect Apple Health": ("health", ("Conectar con Salud", "Conectar ao Saúde", "Mit Apple Health verbinden", "Connecter à Santé", "Apple Sağlık'a bağlan")),
    "Sync your activity and weight so your plan stays accurate. You can change this anytime in Settings.": ("health", (
        "Sincroniza tu actividad y tu peso para que tu plan sea preciso. Puedes cambiarlo en Ajustes cuando quieras.",
        "Sincronize sua atividade e seu peso para manter seu plano preciso. Você pode mudar isso em Ajustes quando quiser.",
        "Synchronisiere Aktivität und Gewicht, damit dein Plan genau bleibt. Du kannst das jederzeit in den Einstellungen ändern.",
        "Synchronise ton activité et ton poids pour garder ton plan précis. Tu peux le modifier à tout moment dans Réglages.",
        "Planın doğru kalsın diye aktiviteni ve kilonu senkronize et. Bunu istediğin zaman Ayarlar'dan değiştirebilirsin.")),
    "Apple Health isn't available on this device.": ("health", (
        "Salud no está disponible en este dispositivo.", "O app Saúde não está disponível neste dispositivo.",
        "Apple Health ist auf diesem Gerät nicht verfügbar.", "Santé n'est pas disponible sur cet appareil.",
        "Apple Sağlık bu cihazda kullanılamıyor.")),
    "Give consent first to connect Apple Health.": ("health", (
        "Da tu consentimiento primero para conectar Salud.", "Dê seu consentimento primeiro para conectar o Saúde.",
        "Gib zuerst deine Einwilligung, um Apple Health zu verbinden.", "Donne d'abord ton consentement pour connecter Santé.",
        "Apple Sağlık'ı bağlamak için önce onay ver.")),
    "Apple Health access is off.": ("health", ("El acceso a Salud está desactivado.", "O acesso ao Saúde está desativado.",
                                               "Der Zugriff auf Apple Health ist aus.", "L'accès à Santé est désactivé.",
                                               "Apple Sağlık erişimi kapalı.")),
    "Some Apple Health permissions are off.": ("health", ("Algunos permisos de Salud están desactivados.", "Algumas permissões do Saúde estão desativadas.",
                                                          "Einige Apple-Health-Berechtigungen sind aus.", "Certaines autorisations Santé sont désactivées.",
                                                          "Bazı Apple Sağlık izinleri kapalı.")),
    "Open Settings": ("health", ("Abrir Ajustes", "Abrir Ajustes", "Einstellungen öffnen", "Ouvrir Réglages", "Ayarlar'ı aç")),
    "Apple Health connected": ("health", ("Salud conectado", "Saúde conectado", "Apple Health verbunden", "Santé connecté", "Apple Sağlık bağlandı")),
    "Apple Health": ("health", ("Salud", "Saúde", "Apple Health", "Santé", "Apple Sağlık")),
    "Credits remaining": ("credits", ("Créditos restantes", "Créditos restantes", "Verbleibende Credits", "Crédits restants", "Kalan kredi")),
    "%lld credits / month": ("credits", ("%lld créditos / mes", "%lld créditos / mês", "%lld Credits / Monat", "%lld crédits / mois", "Ayda %lld kredi")),
    "BEST VALUE": ("credits", ("MEJOR PRECIO", "MELHOR VALOR", "BESTER WERT", "MEILLEUR PRIX", "EN İYİ FİYAT")),
    "Credit packs are a one-time purchase. They never expire.": ("credits", (
        "Los paquetes de créditos son una compra única. No caducan.", "Os pacotes de créditos são uma compra única. Eles não expiram.",
        "Credit-Pakete sind ein einmaliger Kauf. Sie verfallen nie.", "Les packs de crédits sont un achat unique. Ils n'expirent jamais.",
        "Kredi paketleri tek seferlik satın alımdır. Süreleri dolmaz.")),
    "credits": ("credits", ("créditos", "créditos", "Credits", "crédits", "kredi")),
    "Top up now to keep creating.": ("credits", ("Recarga ahora para seguir creando.", "Recarregue agora para continuar criando.",
                                                 "Lade jetzt auf, um weiter zu erstellen.", "Recharge maintenant pour continuer à créer.",
                                                 "Oluşturmaya devam etmek için şimdi yükle.")),
    "Upgrade to Yearly": ("credits", ("Cambiar al plan anual", "Mudar para o anual", "Auf jährlich upgraden", "Passer à l'annuel", "Yıllığa geç")),
    "You're out of credits": ("credits", ("Te quedaste sin créditos", "Seus créditos acabaram", "Deine Credits sind aufgebraucht",
                                          "Tu n'as plus de crédits", "Kredin bitti")),
    "Your credits refill %@": ("credits", ("Tus créditos se recargan %@", "Seus créditos são renovados %@", "Deine Credits werden %@ aufgefüllt",
                                           "Tes crédits se rechargent %@", "Kredilerin %@ yenilenir")),
}


def unit(value: str) -> dict:
    return {"stringUnit": {"state": "translated", "value": value}}


def build(catalog_path: str) -> dict:
    try:
        with open(catalog_path, encoding="utf-8") as f:
            cat = json.load(f)
    except FileNotFoundError:
        cat = {"sourceLanguage": "en", "strings": {}, "version": "1.0"}
    strings = cat.setdefault("strings", {})

    def put(key, values, en=None, comment=None):
        entry = strings.setdefault(key, {"extractionState": "manual"})
        if comment:
            entry["comment"] = comment
        locs = entry.setdefault("localizations", {})
        if en is not None:
            locs.setdefault("en", unit(en))
        for lang, value in zip(LANGS, values):
            locs.setdefault(lang, unit(value))

    for key, values in T.items():
        put(key, values)
    for key, (en, *values) in SEMANTIC.items():
        put(key, values, en=en, comment="Offer paywall price anchor (spec offer_anchor.label_key)")
    for key, (flag, values) in MODULE.items():
        put(key, values, comment=f"[module:{flag}]")
    return cat


if __name__ == "__main__":
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Resources", "Localizable.xcstrings")
    cat = build(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cat, f, ensure_ascii=False, indent=2, separators=(",", " : "), sort_keys=True)
        f.write("\n")
    print(f"{len(cat['strings'])} keys")
