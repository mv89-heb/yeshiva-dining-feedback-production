(function(){
  const form=document.getElementById('student-feedback-form');
  if(!form)return;
  const mealRadios=Array.from(form.querySelectorAll('input[name="meal_type"]'));
  const localDate=document.getElementById('meal_date');
  const mainRoot=document.getElementById('main-dishes');
  const sideRoot=document.getElementById('side-dishes');
  const status=document.getElementById('menu-status');
  const retry=document.getElementById('retry-menu');
  const dishPanel=document.getElementById('dish-panel');
  const submit=document.getElementById('submit-feedback');
  const catalog=JSON.parse(document.getElementById('menu-catalog').textContent||'[]');
  const lang=document.documentElement.lang==='he'?'he':'en';
  const words={
    en:{loading:"Loading the menu…",empty:"No dishes are scheduled for this meal. Please contact the dining team.",fallback:"The full dish list is shown because no menu has been configured yet.",failed:"We couldn't load the menu. Check your connection and try again.",main:"Main dishes",side:"Side dishes",rate:"Rate this dish"},
    he:{loading:"טוען את התפריט…",empty:"לא הוגדרו מנות לארוחה זו. פנו לצוות חדר האוכל.",fallback:"מוצג מאגר המנות המלא כי עדיין לא הוגדר תפריט.",failed:"לא הצלחנו לטעון את התפריט. בדקו את החיבור ונסו שוב.",main:"מנות עיקריות",side:"תוספות",rate:"דרגו את המנה"}
  };
  let activeController=null;
  let requestSequence=0;
  function setLocalDate(){
    const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Jerusalem',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
    const value=type=>parts.find(part=>part.type===type).value;
    localDate.value=value('year')+'-'+value('month')+'-'+value('day');
  }
  function selectedMeal(){
    const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Jerusalem',hour:'2-digit',hourCycle:'h23'}).formatToParts(new Date());
    const hour=Number(parts.find(part=>part.type==='hour').value);
    return hour>=5&&hour<10?'breakfast':hour>=10&&hour<16?'lunch':'dinner';
  }
  function renderDish(item){
    const card=document.createElement('div');card.className='dish-item';
    const checkLabel=document.createElement('label');checkLabel.className='dish-item-choice';
    const check=document.createElement('input');check.type='checkbox';check.name='dish_slug';check.value=item.slug;
    const title=document.createElement('span');title.textContent=lang==='he'?item.he:item.en;
    checkLabel.append(check,title);card.append(checkLabel);
    const ratings=document.createElement('fieldset');ratings.className='dish-item-rating';ratings.disabled=true;
    const legend=document.createElement('legend');legend.textContent=words[lang].rate;ratings.append(legend);
    const row=document.createElement('div');row.className='dish-stars';
    for(let value=1;value<=5;value++){
      const label=document.createElement('label');
      const radio=document.createElement('input');radio.type='radio';radio.name='dish_rating_'+item.slug;radio.value=String(value);radio.required=true;
      const star=document.createElement('span');star.textContent='★';star.setAttribute('aria-hidden','true');
      const number=document.createElement('small');number.textContent=String(value);
      label.append(radio,star,number);row.append(label);
    }
    ratings.append(row);card.append(ratings);
    check.addEventListener('change',()=>{
      ratings.disabled=!check.checked;
      ratings.querySelectorAll('input').forEach(radio=>{radio.required=check.checked;if(!check.checked)radio.checked=false;});
      card.classList.toggle('is-selected',check.checked);
    });
    return card;
  }
  async function loadMenu(){
    if(activeController)activeController.abort();
    const controller=new AbortController();
    activeController=controller;
    const sequence=++requestSequence;
    const meal=mealRadios.find(radio=>radio.checked)?.value||'lunch';
    status.textContent=words[lang].loading;
    retry.hidden=true;
    mainRoot.replaceChildren();sideRoot.replaceChildren();
    const mainHeading=document.createElement('h3');mainHeading.textContent=words[lang].main;mainRoot.append(mainHeading);
    const sideHeading=document.createElement('h3');sideHeading.textContent=words[lang].side;sideRoot.append(sideHeading);
    try{
      const response=await fetch('/api/menu?date='+encodeURIComponent(localDate.value)+'&meal_type='+encodeURIComponent(meal),{
        headers:{Accept:'application/json'},cache:'no-store',signal:controller.signal
      });
      if(!response.ok)throw new Error('menu request failed');
      const payload=await response.json();
      if(sequence!==requestSequence)return;
      let items=payload.dishes||[];
      if(!payload.configured){
        items=catalog.map(dish=>({slug:dish[0],he:dish[1],en:dish[2],category:'main'}));
        status.textContent=words[lang].fallback;
      }else status.textContent='';
      items.forEach(item=>(item.category==='side'?sideRoot:mainRoot).append(renderDish(item)));
      if(!items.length)status.textContent=words[lang].empty;
    }catch(error){
      if(error.name==='AbortError'||sequence!==requestSequence)return;
      status.textContent=words[lang].failed;
      retry.hidden=false;
    }
  }
  setLocalDate();
  const selected=selectedMeal();
  const radio=mealRadios.find(item=>item.value===selected);
  if(radio)radio.checked=true;
  mealRadios.forEach(item=>item.addEventListener('change',loadMenu));
  retry.addEventListener('click',loadMenu);
  loadMenu();
  form.addEventListener('submit',event=>{
    const selectedDishes=Array.from(form.querySelectorAll('input[name="dish_slug"]:checked'));
    const missing=selectedDishes.find(check=>!form.querySelector('input[name="dish_rating_'+CSS.escape(check.value)+'"]:checked'));
    if(!selectedDishes.length||missing){
      event.preventDefault();
      dishPanel.classList.add('dish-needs-attention');
      const target=missing
        ?form.querySelector('input[name="dish_rating_'+CSS.escape(missing.value)+'"]')
        :form.querySelector('input[name="dish_slug"]');
      if(target)target.focus();
      status.textContent=lang==='he'?'יש לבחור לפחות מנה אחת ולדרג כל מנה שסומנה.':'Select at least one dish and rate every selected dish.';
      return;
    }
    submit.disabled=true;
    submit.querySelector('span').textContent=lang==='he'?'שולח…':'Sending…';
    submit.setAttribute('aria-busy','true');
  });
})();