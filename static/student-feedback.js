(function(){
  const form=document.getElementById('student-feedback-form');
  if(!form)return;
  const mealRadios=Array.from(form.querySelectorAll('input[name="meal_type"]'));
  const localDate=document.getElementById('meal_date');
  const mainRoot=document.getElementById('main-dishes');
  const sideRoot=document.getElementById('side-dishes');
  const status=document.getElementById('menu-status');
  const dishPanel=document.getElementById('dish-panel');
  const submit=document.getElementById('submit-feedback');
  const catalog=JSON.parse(document.getElementById('menu-catalog').textContent||'[]');
  const words={en:{loading:"Loading the menu…",empty:"No menu is configured for this meal yet. Please contact the dining team.",main:"Main dishes",side:"Side dishes",ate:"I ate this",rate:"Rate this dish",notAte:"Leave unchecked if you did not eat it."},he:{loading:"טוען את התפריט…",empty:"עדיין לא הוגדר תפריט לארוחה זו. פנו לצוות חדר האוכל.",main:"מנות עיקריות",side:"תוספות",ate:"אכלתי את המנה",rate:"דרגו את המנה",notAte:"אם לא אכלתם, השאירו ללא סימון."}};
  const lang=document.documentElement.lang==='he'?'he':'en';
  function setLocalDate(){
    const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Jerusalem',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
    const val=t=>parts.find(p=>p.type===t).value;
    localDate.value=val('year')+'-'+val('month')+'-'+val('day');
  }
  function selectedMeal(){
    const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Jerusalem',hour:'2-digit',hourCycle:'h23'}).formatToParts(new Date());
    const hour=Number(parts.find(p=>p.type==='hour').value);
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
    for(let n=1;n<=5;n++){
      const label=document.createElement('label');const radio=document.createElement('input');
      radio.type='radio';radio.name='dish_rating_'+item.slug;radio.value=String(n);radio.required=true;
      const star=document.createElement('span');star.textContent='★';star.setAttribute('aria-hidden','true');
      const number=document.createElement('small');number.textContent=String(n);
      label.append(radio,star,number);row.append(label);
    }
    ratings.append(row);card.append(ratings);
    check.addEventListener('change',()=>{ratings.disabled=!check.checked;ratings.querySelectorAll('input').forEach(r=>{r.required=check.checked;if(!check.checked)r.checked=false;});});
    return card;
  }
  async function loadMenu(){
    const meal=mealRadios.find(r=>r.checked)?.value||'lunch';
    status.textContent=words[lang].loading;mainRoot.replaceChildren();sideRoot.replaceChildren();
    const mainHeading=document.createElement('h3');mainHeading.textContent=words[lang].main;mainRoot.append(mainHeading);
    const sideHeading=document.createElement('h3');sideHeading.textContent=words[lang].side;sideRoot.append(sideHeading);
    try{
      const response=await fetch('/api/menu?date='+encodeURIComponent(localDate.value)+'&meal_type='+encodeURIComponent(meal),{headers:{Accept:'application/json'},cache:'no-store'});
      if(!response.ok)throw new Error('menu request failed');
      const payload=await response.json();
      let items=payload.dishes||[];
      if(!payload.configured){
        items=catalog.map(d=>({slug:d[0],he:d[1],en:d[2],category:'main'}));
        status.textContent=words[lang].empty;
      }else status.textContent='';
      items.forEach(item=>(item.category==='side'?sideRoot:mainRoot).append(renderDish(item)));
      if(!items.length)status.textContent=words[lang].empty;
    }catch(_error){status.textContent=words[lang].empty;}
  }
  setLocalDate();
  const chosen=selectedMeal();const radio=mealRadios.find(r=>r.value===chosen);if(radio)radio.checked=true;
  mealRadios.forEach(r=>r.addEventListener('change',loadMenu));
  loadMenu();
  form.addEventListener('submit',function(event){
    const selected=Array.from(form.querySelectorAll('input[name="dish_slug"]:checked'));
    const missing=selected.some(check=>!form.querySelector('input[name="dish_rating_'+CSS.escape(check.value)+'"]:checked'));
    if(!selected.length||missing){
      event.preventDefault();dishPanel.classList.add('dish-needs-attention');
      const target=missing?form.querySelector('input[name="dish_rating_'+CSS.escape(selected.find(check=>!form.querySelector('input[name="dish_rating_'+CSS.escape(check.value)+'"]:checked')).value)+'"]'):form.querySelector('input[name="dish_slug"]');
      if(target)target.focus();
      status.textContent=lang==='he'?'יש לבחור לפחות מנה אחת ולדרג כל מנה שסומנה.':'Select at least one dish and rate every selected dish.';
      return;
    }
    submit.disabled=true;submit.querySelector('span').textContent=lang==='he'?'שולח…':'Sending…';submit.setAttribute('aria-busy','true');
  });
})();